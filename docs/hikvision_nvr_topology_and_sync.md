# Hikvision Kamerový systém & NVR Master Synchronizace (NM315)

Tento dokument kodifikuje pravidla, síťovou topologii a postupy pro správu kamer Hikvision a NVR v prostředí NM315 integrovaném s `smtp2mqtt` a Loxone.

---

## 1. Pravidlo NVR Master Synchronizace (Anti-Overwrite Rule)

Kamery jsou k NVR (`10.0.40.100`) připojeny přes proprietární protokol `HIKVISION` (port 8000). V této architektuře funguje **NVR jako nadřazený Master**.

> [!WARNING]
> Při každém restartu, uložení z webu NVR nebo pravidelném resyncu NVR automaticky přepíše konfiguraci detekčních zón (`LineDetection`, `FieldDetection`, `motionDetection`) v připojených kamerách daty ze své vlastní databáze.
>
> **Závazný postup:** Jakékoliv Smart Event linie, polygony nebo citlivosti detekce **musí být VŽDY uloženy a zapsány přímo do NVR** (`/ISAPI/Smart/.../<ch_id>` a `/ISAPI/System/Video/inputs/channels/<ch_id>/...`), nikoliv pouze do jednotlivých IP kamer.

---

## 2. Přehled kamerové topologie a nočních režimů

| Kanál | Kamera | IP adresa | Model | Noční režim / Přísvit | Detekční linie & Pravidla |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **NVR** | **Master NVR** | `10.0.40.100` | Hikvision NVR | N/A (`admin` / `CKmoran315cam`) | Centrální správa všech kanálů |
| **1** | **Střecha** | `10.0.40.101` | Klasická IR kamera | Standardní IR (`auto`) | VMD aktivní (citlivost 60, `all`) |
| **2** | **Parking** | `10.0.40.102` | AcuSense | `irLight` (čisté IR) | VMD aktivní (citlivost 20, `all`) |
| **3** | **Vchod** | `10.0.40.103` | `DS-2CD2387G2-LSU/SL` (ColorVu Live-Guard) | **`close`** (zhasnutý přísvit, spoléhá na F1.0 + lampu, neoslňuje ulici) | **LineDetection L1–L4** (sens 85, filter `human`, confidence `high`) |
| **4** | **Zahrada** | `10.0.40.104` | `DS-2CD2087G2H-LIU` (Smart Hybrid Light) | **`irLight`** (výkon 80 %, čisté IR bez bílého LED reflektoru) | **LineDetection L1–L3** (sens 85, filter `human`, confidence `high`) |

---

## 3. Klíčové ISAPI Příkazy pro synchronizaci

### Nastavení LineDetection na NVR pro kanál 4 (Zahrada):
```http
PUT /ISAPI/Smart/LineDetection/4 HTTP/1.1
Host: 10.0.40.100
Content-Type: application/xml
Authorization: Digest admin:CKmoran315cam

<?xml version="1.0" encoding="UTF-8"?>
<LineDetection version="1.0" xmlns="http://www.hikvision.com/ver20/XMLSchema">
<id>4</id>
<enabled>true</enabled>
<normalizedScreenSize>
<normalizedScreenWidth>1000</normalizedScreenWidth>
<normalizedScreenHeight>1000</normalizedScreenHeight>
</normalizedScreenSize>
<LineItemList size="4">
<LineItem>
<id>1</id>
<enabled>true</enabled>
<sensitivityLevel>85</sensitivityLevel>
<directionSensitivity>any</directionSensitivity>
<CoordinatesList>
<Coordinates><positionX>699</positionX><positionY>657</positionY></Coordinates>
<Coordinates><positionX>736</positionX><positionY>699</positionY></Coordinates>
</CoordinatesList>
<detectionTarget>human</detectionTarget>
<alarmConfidence>high</alarmConfidence>
</LineItem>
...
</LineItemList>
</LineDetection>
```

### Nastavení IR přísvitu na kameře Zahrada (`10.0.40.104`):
```http
PUT /ISAPI/Image/channels/1/supplementLight HTTP/1.1
Host: 10.0.40.104
Content-Type: application/xml
Authorization: Digest admin:ckmoran315cam

<?xml version="1.0" encoding="UTF-8"?>
<SupplementLight version="2.0" xmlns="http://www.hikvision.com/ver20/XMLSchema">
<supplementLightMode>irLight</supplementLightMode>
<irLightBrightness>80</irLightBrightness>
<mixedLightBrightnessRegulatMode>auto</mixedLightBrightnessRegulatMode>
</SupplementLight>
```
