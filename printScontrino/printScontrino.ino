#if !defined(ARDUINO_ARCH_ESP32)
#error This sketch targets ESP32 boards with Wi-Fi and a hardware UART connected to the printer.
#endif

#include <Arduino.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <time.h>

#include "title_bitmap.h"
#include "cornetto_bitmap.h"
#include "secrets.h"

namespace {
constexpr char PRINTER_ID[] = "totem-01";

constexpr uint32_t POLL_INTERVAL_MS = 5000;
constexpr uint32_t WIFI_RETRY_DELAY_MS = 500;
constexpr uint32_t WIFI_CONNECT_TIMEOUT_MS = 20000;
constexpr uint32_t HTTP_TIMEOUT_MS = 12000;
constexpr uint32_t PRINTER_STATUS_TIMEOUT_MS = 800;

// Typical effective print width for 58mm thermal printers.
constexpr uint16_t PRINTER_MAX_WIDTH_DOTS = 384;

// Confirmed via baud scan.
constexpr int PRINTER_BAUD_RATE = 19200;

// Wiring: printer RX <-> ESP32 D6, printer TX <-> ESP32 D7.
constexpr int PRINTER_RX_PIN = D7;  // ESP32 receives here <- printer TXD
constexpr int PRINTER_TX_PIN = D6;  // ESP32 transmits here -> printer RXD

constexpr bool REQUIRE_PRINTER_STATUS_RESPONSE = true;

HardwareSerial printerSerial(1);
WiFiClientSecure secureClient;

struct Registration {
  int id = -1;
  String createdAt;
  String eventName;
  String attendeeName;
  String attendeeEmail;
  String speakerNames[8];
  size_t speakerCount = 0;
};

unsigned long lastPollAt = 0;

void logLine(const String &message) {
  Serial.println(message);
}

bool ensureWiFiConnected() {
  if (WiFi.status() == WL_CONNECTED) {
    return true;
  }

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  const unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < WIFI_CONNECT_TIMEOUT_MS) {
    delay(WIFI_RETRY_DELAY_MS);
    Serial.print('.');
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println();
    logLine("Wi-Fi connected: " + WiFi.localIP().toString());
    return true;
  }

  Serial.println();
  logLine("Wi-Fi connection failed.");
  WiFi.disconnect(true, true);
  return false;
}

bool ensureClockSynced() {
  time_t now = time(nullptr);
  if (now > 1700000000) {
    return true;
  }

  configTime(0, 0, "pool.ntp.org", "time.nist.gov", "time.google.com");
  const unsigned long start = millis();

  while (millis() - start < 15000) {
    now = time(nullptr);
    if (now > 1700000000) {
      logLine("Clock synchronized.");
      return true;
    }
    delay(250);
  }

  logLine("Unable to synchronize clock via NTP.");
  return false;
}

bool beginRequest(HTTPClient &http, const String &url) {
  secureClient.setInsecure();
  if (!http.begin(secureClient, url)) {
    logLine("HTTP begin failed.");
    return false;
  }

  http.setTimeout(HTTP_TIMEOUT_MS);
  http.addHeader("apikey", SUPABASE_ANON_KEY);
  http.addHeader("Authorization", String("Bearer ") + SUPABASE_ANON_KEY);
  http.addHeader("Accept", "application/json");
  return true;
}

bool fetchNextPendingRegistration(Registration &registration) {
  HTTPClient http;
  const String url =
    String(SUPABASE_URL) +
    "/rest/v1/registrations"
    "?select=id%2Ccreated_at%2Cevent_name%2Cattendee_name%2Cattendee_email%2Cspeaker_names"
    "&print_status=eq.pending"
    "&order=created_at.asc"
    "&limit=1";

  if (!beginRequest(http, url)) {
    return false;
  }

  const int statusCode = http.GET();
  const String payload = http.getString();
  http.end();

  if (statusCode != HTTP_CODE_OK) {
    logLine("Supabase GET failed: " + String(statusCode) + " " + payload);
    return false;
  }

  DynamicJsonDocument document(4096);
  DeserializationError error = deserializeJson(document, payload);
  if (error) {
    logLine("Unable to parse GET payload: " + String(error.c_str()));
    return false;
  }

  JsonArray rows = document.as<JsonArray>();
  if (rows.isNull() || rows.size() == 0) {
    logLine("No pending registrations found.");
    return false;
  }

  JsonObject row = rows[0];
  registration.id = row["id"] | -1;
  registration.createdAt = String((const char *)(row["created_at"] | ""));
  registration.eventName = String((const char *)(row["event_name"] | ""));
  registration.attendeeName = String((const char *)(row["attendee_name"] | ""));
  registration.attendeeEmail = String((const char *)(row["attendee_email"] | ""));
  registration.speakerCount = 0;

  JsonArray speakers = row["speaker_names"].as<JsonArray>();
  if (!speakers.isNull()) {
    for (JsonVariant value : speakers) {
      if (registration.speakerCount >= (sizeof(registration.speakerNames) / sizeof(registration.speakerNames[0]))) {
        break;
      }

      registration.speakerNames[registration.speakerCount++] = String((const char *)(value | ""));
    }
  }

  return registration.id >= 0;
}

bool patchRegistrationPrinted(int registrationId) {
  auto isStillPending = [&]() {
    HTTPClient verifyHttp;
    const String verifyUrl =
      String(SUPABASE_URL) +
      "/rest/v1/registrations"
      "?select=id"
      "&id=eq." + String(registrationId) +
      "&print_status=eq.pending"
      "&limit=1";

    if (!beginRequest(verifyHttp, verifyUrl)) {
      logLine("Pending-check HTTP begin failed.");
      return true;
    }

    const int verifyStatusCode = verifyHttp.GET();
    const String verifyPayload = verifyHttp.getString();
    verifyHttp.end();

    if (verifyStatusCode != HTTP_CODE_OK) {
      logLine("Pending-check GET failed: " + String(verifyStatusCode) + " " + verifyPayload);
      return true;
    }

    DynamicJsonDocument verifyDocument(512);
    DeserializationError verifyError = deserializeJson(verifyDocument, verifyPayload);
    if (verifyError) {
      logLine("Unable to parse pending-check payload: " + String(verifyError.c_str()));
      return true;
    }

    JsonArray rows = verifyDocument.as<JsonArray>();
    return !rows.isNull() && rows.size() > 0;
  };

  auto tryPatch = [&](const String &url, bool withPendingFilter, bool includePrinterId) {
    HTTPClient http;

    if (!beginRequest(http, url)) {
      return false;
    }

    http.addHeader("Content-Type", "application/json");
    http.addHeader("Prefer", "return=representation");

    StaticJsonDocument<192> bodyDocument;
    bodyDocument["print_status"] = "printed";
    if (includePrinterId) {
      bodyDocument["printer_id"] = PRINTER_ID;
    }

    String body;
    serializeJson(bodyDocument, body);

    const int statusCode = http.PATCH(body);
    const String payload = http.getString();
    http.end();

    if (statusCode != HTTP_CODE_OK && statusCode != HTTP_CODE_NO_CONTENT) {
      const String scope = withPendingFilter ? "pending filter" : "fallback";
      const String bodyKind = String("print_status") + (includePrinterId ? "+printer_id" : "");
      logLine("Supabase PATCH failed (" + scope + ", body=" + bodyKind + "): " + String(statusCode) + " " + payload);
      return false;
    }

    // With some RLS setups, return=representation can be [] even when UPDATE succeeded.
    if (statusCode == HTTP_CODE_OK && payload == "[]") {
      if (!isStillPending()) {
        logLine("Supabase PATCH returned [], but registration is no longer pending (treated as success).");
        return true;
      }

      logLine("Supabase PATCH matched 0 rows" + String(withPendingFilter ? " (pending filter)." : " (fallback)."));
      return false;
    }

    return true;
  };

  const String baseUrl = String(SUPABASE_URL) + "/rest/v1/registrations?id=eq." + String(registrationId);
  const String pendingUrl = baseUrl + "&print_status=eq.pending";

  if (tryPatch(pendingUrl, true, true) ||
      tryPatch(pendingUrl, true, false) ||
      tryPatch(baseUrl, false, true) ||
      tryPatch(baseUrl, false, false)) {
    logLine("Registration " + String(registrationId) + " marked as printed.");
    return true;
  }

  return false;
}

void sendPrinterCommand(const uint8_t *bytes, size_t length) {
  printerSerial.write(bytes, length);
  printerSerial.flush();
}

void printerReset() {
  static const uint8_t command[] = {0x1B, 0x40};
  sendPrinterCommand(command, sizeof(command));
}

void printerSetAlign(uint8_t align) {
  const uint8_t command[] = {0x1B, 0x61, align};
  sendPrinterCommand(command, sizeof(command));
}

void printerSetBold(bool enabled) {
  const uint8_t command[] = {0x1B, 0x45, static_cast<uint8_t>(enabled ? 1 : 0)};
  sendPrinterCommand(command, sizeof(command));
}

void printerSetTextSize(uint8_t size) {
  const uint8_t command[] = {0x1D, 0x21, size};
  sendPrinterCommand(command, sizeof(command));
}

void printerFeed(uint8_t lines) {
  const uint8_t command[] = {0x1B, 0x64, lines};
  sendPrinterCommand(command, sizeof(command));
}

void printerCut() {
  static const uint8_t command[] = {0x1D, 0x56, 0x42, 0x00};
  sendPrinterCommand(command, sizeof(command));
}

void printerPrintRasterImage(const uint8_t *bitmapData, uint16_t widthPixels, uint16_t heightPixels) {
  const uint16_t bytesPerRow = (widthPixels + 7) / 8;

  const uint8_t header[] = {
    0x1D,
    0x76,
    0x30,
    0x00,
    static_cast<uint8_t>(bytesPerRow & 0xFF),
    static_cast<uint8_t>((bytesPerRow >> 8) & 0xFF),
    static_cast<uint8_t>(heightPixels & 0xFF),
    static_cast<uint8_t>((heightPixels >> 8) & 0xFF),
  };

  sendPrinterCommand(header, sizeof(header));

  for (uint32_t index = 0; index < static_cast<uint32_t>(bytesPerRow) * heightPixels; ++index) {
    printerSerial.write(pgm_read_byte(bitmapData + index));
  }

  printerSerial.flush();
}

void printerPrintRasterImageCentered(const uint8_t *bitmapData, uint16_t widthPixels, uint16_t heightPixels) {
  uint16_t targetWidthDots = PRINTER_MAX_WIDTH_DOTS;
  if (targetWidthDots < widthPixels) {
    targetWidthDots = widthPixels;
  }

  const uint16_t srcBytesPerRow = (widthPixels + 7) / 8;
  const uint16_t dstBytesPerRow = (targetWidthDots + 7) / 8;
  const uint16_t extraBytes = dstBytesPerRow - srcBytesPerRow;
  const uint16_t leftPadBytes = extraBytes / 2;
  const uint16_t rightPadBytes = extraBytes - leftPadBytes;

  const uint8_t header[] = {
    0x1D,
    0x76,
    0x30,
    0x00,
    static_cast<uint8_t>(dstBytesPerRow & 0xFF),
    static_cast<uint8_t>((dstBytesPerRow >> 8) & 0xFF),
    static_cast<uint8_t>(heightPixels & 0xFF),
    static_cast<uint8_t>((heightPixels >> 8) & 0xFF),
  };

  sendPrinterCommand(header, sizeof(header));

  for (uint16_t row = 0; row < heightPixels; ++row) {
    for (uint16_t i = 0; i < leftPadBytes; ++i) {
      printerSerial.write(static_cast<uint8_t>(0x00));
    }

    const uint32_t rowOffset = static_cast<uint32_t>(row) * srcBytesPerRow;
    for (uint16_t i = 0; i < srcBytesPerRow; ++i) {
      printerSerial.write(pgm_read_byte(bitmapData + rowOffset + i));
    }

    for (uint16_t i = 0; i < rightPadBytes; ++i) {
      printerSerial.write(static_cast<uint8_t>(0x00));
    }
  }

  printerSerial.flush();
}

// ESC v n - Transmit paper sensor status [file:1].
bool queryPrinterStatus(uint8_t &statusByte) {
  while (printerSerial.available() > 0) {
    printerSerial.read();
  }

  const uint8_t command[] = {0x1B, 0x76, 0x00};
  sendPrinterCommand(command, sizeof(command));

  const unsigned long start = millis();
  while (millis() - start < PRINTER_STATUS_TIMEOUT_MS) {
    if (printerSerial.available() > 0) {
      statusByte = static_cast<uint8_t>(printerSerial.read());
      return true;
    }
    delay(10);
  }

  return false;
}

// FIX: This board has no head-cover microswitch, so bit 0 (online/offline)
// of the ESC v n response is not a reliable signal here -- the printer's own
// front-panel LED (single blink = "Work well") already confirms it is
// mechanically fine even when this bit reads 0. We stop gating prints on
// isOnline and only block on paper-out and low-voltage, which are the two
// conditions that genuinely prevent a successful print on this hardware.
bool checkPrinterReady(bool &hasPaper, bool &voltageOk) {
  uint8_t statusByte = 0;
  const bool gotResponse = queryPrinterStatus(statusByte);

  if (!gotResponse) {
    logLine("Printer status query timed out.");
    hasPaper = !REQUIRE_PRINTER_STATUS_RESPONSE;
    voltageOk = !REQUIRE_PRINTER_STATUS_RESPONSE;
    return !REQUIRE_PRINTER_STATUS_RESPONSE;
  }

  const bool isOnlineBit = (statusByte & 0x01) != 0;
  hasPaper = (statusByte & 0x04) == 0;
  voltageOk = (statusByte & 0x08) == 0;

  // Logged for visibility only; intentionally not used to fail the print.
  if (!isOnlineBit) {
    logLine("Note: online bit reads offline (ignored on this hardware, no cover switch). Status byte: " + String(statusByte, HEX));
  }
  if (!hasPaper) {
    logLine("Printer reports paper out. Status byte: " + String(statusByte, HEX));
  }
  if (!voltageOk) {
    logLine("Printer reports low voltage (< 9.5V). Status byte: " + String(statusByte, HEX));
  }

  return hasPaper && voltageOk;
}

bool printReceipt(const Registration &registration) {
  printerReset();
  delay(100);

  printerSetAlign(1);
  printerPrintRasterImage(TITLE_BITMAP_DATA, TITLE_BITMAP_WIDTH, TITLE_BITMAP_HEIGHT);
  printerFeed(1);

  printerSetTextSize(0x00);
  printerSetBold(false);
  printerFeed(1);
  printerSerial.println(registration.eventName);
  printerSerial.println("17.09.2026");
  printerFeed(1);

  if (registration.speakerCount > 0) {
    printerFeed(1);
    printerSetBold(true);
    printerSerial.println("Relatori");
    printerSetBold(false);

    for (size_t index = 0; index < registration.speakerCount; ++index) {
      printerSerial.println(registration.speakerNames[index]);
    }
  }

  printerFeed(1);
  printerSetAlign(0);
  printerSetBold(true);
  printerSerial.println("ISCRIZIONE CONFERMATA");
  printerSetBold(false);
  printerSerial.println("--------------------------------");
  printerSerial.println("Nome: " + registration.attendeeName);
  printerSerial.println("Email: " + registration.attendeeEmail);
  printerSerial.println("Registrazione ID: " + String(registration.id));
  printerSerial.println("Creata il: " + registration.createdAt);
  printerSerial.println("--------------------------------");
  printerFeed(1);

  printerSetAlign(1);
  printerPrintRasterImageCentered(CORNETTO_BITMAP_DATA, CORNETTO_BITMAP_WIDTH, CORNETTO_BITMAP_HEIGHT);
  printerFeed(1);

  printerSetAlign(1);
  printerFeed(2);
  printerSerial.println("CONSERVA QUESTO SCONTRINO");
  printerFeed(5);
  printerCut();
  printerSerial.flush();
  delay(500);

  return true;
}

void setupImpl() {
  Serial.begin(115200);
  delay(250);

  printerSerial.begin(PRINTER_BAUD_RATE, SERIAL_8N1, PRINTER_RX_PIN, PRINTER_TX_PIN);
  logLine("Booting printer polling service...");

  ensureWiFiConnected();
  ensureClockSynced();
}

void loopImpl() {
  if (millis() - lastPollAt < POLL_INTERVAL_MS) {
    delay(50);
    return;
  }

  lastPollAt = millis();

  if (!ensureWiFiConnected()) {
    return;
  }

  if (!ensureClockSynced()) {
    logLine("Clock not synced; continuing print/update flow anyway.");
  }

  Registration registration;
  if (!fetchNextPendingRegistration(registration)) {
    return;
  }

  logLine("Printing registration ID " + String(registration.id) + " for " + registration.attendeeName);

  printReceipt(registration);

  if (!patchRegistrationPrinted(registration.id)) {
    logLine("Printed successfully, but Supabase update failed for registration ID " + String(registration.id));
    return;
  }

  logLine("Completed job for registration ID " + String(registration.id) + ".");
}

}  // namespace

void setup() {
  setupImpl();
}

void loop() {
  loopImpl();
}