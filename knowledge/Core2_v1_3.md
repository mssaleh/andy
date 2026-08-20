# Core2 v1.3

<span class="product-sku">SKU:K010-V13</span>

<PictureViewer>
<img src="https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/1231/K010-V13-Core2-v1.3-main-pictures_01.webp">
<img src="https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/1231/K010-V13-Core2-v1.3-main-pictures_02.webp">
<img src="https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/1231/K010-V13-Core2-v1.3-main-pictures_03.webp">
<img src="https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/1231/K010-V13-Core2-v1.3-main-pictures_04.webp">
<img src="https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/1231/K010-V13-Core2-v1.3-main-pictures_05.webp">
<img src="https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/1231/K010-V13-Core2-v1.3-main-pictures_06.webp">
<img src="https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/1231/K010-V13-Core2-v1.3-main-pictures_07.webp">
<img src="https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/1231/K010-V13-Core2-v1.3-main-pictures_08.webp">
<img src="https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/1231/K010-V13-Core2-v1.3-main-pictures_09.webp">
<img src="https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/1231/K010-V13-Core2-v1.3-main-pictures_10.webp">
<img src="https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/1231/K010-V13-Core2-v1.3-main-pictures_11.webp">
<img src="https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/1231/K010-V13-Core2-v1.3-main-pictures_12.webp">
<img src="https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/1231/K010-V13-Core2-v1.3-main-pictures_13.webp">
<img src="https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/1231/K010-V13-Core2-v1.3-main-pictures_14.webp">
<img src="https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/1231/K010-V13-weight.jpg">
</PictureViewer>

## Description

Core2 v1.3 is a highly integrated controller designed for IoT applications. It features the ESP32-D0WDQ6-V3 core with an Xtensa dual-core 32-bit LX6 processor running at 240 MHz. The board includes 16MB of Flash, 8MB of PSRAM, and supports 2.4 GHz Wi-Fi. This version is an iteration of Core2 v1.0, retaining the AXP192 power management IC while upgrading the 6-axis IMU on the rear expansion board to a BMI270, which improves pose detection accuracy and overall performance without compromising system architecture or compatibility. For human-machine interaction, the device features a 2.0" color capacitive touchscreen. The three dot-shaped touch zones on the front panel are programmable and can be mapped to three virtual buttons. A built-in vibration motor provides tactile feedback. For storage and audio, the board includes a microSD card slot and a speaker, with audio output delivered via an I2S digital interface through the NS4168 amplifier to minimize distortion and enhance sound quality. The device also integrates an RTC real-time clock IC and a 500mAh lithium battery. The rear expansion board incorporates a BMI270 6-axis IMU and a microphone, supporting motion sensing and audio capture. This product is well-suited for IoT terminals, human-machine interaction devices, pose detection, and embedded multi-function development applications.

## Tutorial

learn>| ![UiFlow](https://m5stack.oss-cn-shenzhen.aliyuncs.com/resource/docs/static/assets/img/uiflow/uiflow1.0_banner_01.png) | [UiFlow](/en/uiflow/m5core2/program) | This tutorial explains how to control the Core2 device using the UiFlow graphical programming platform. |

learn>| ![UiFlow2](https://m5stack.oss-cn-shenzhen.aliyuncs.com/resource/docs/static/assets/img/uiflow2/uiflow2.0_banner_01.png) | [UiFlow2](/en/uiflow2/m5core2/program) | This tutorial explains how to control the Core2 device using the UiFlow2 graphical programming platform. |

learn>| ![Arduino IDE](https://m5stack.oss-cn-shenzhen.aliyuncs.com/resource/docs/static/assets/img/arduino/arduino_banner_01.png) | [Arduino IDE](/en/arduino/m5core2/program) | This tutorial explains how to program and control the Core2 device using the Arduino IDE. |

<!--Note: links have been replaced-->

### Notes

- The built-in vibration motor of Core2 v1.3 has a structural interference with Base series bases. To prevent damage to the device, do not stack Core2 v1.3 with any Base series expansion base.
- When stacking Core2 v1.3 with M5 modules, you will need to remove the battery bottom of Core2 v1.3. If you need to retain the I2S microphone, IMU, and battery functions of the base while stacking additional modules, it is recommended to use the [M5GO Bottom2](/en/base/m5go_bottom2).
- Some screen edges may exhibit touch non-linearity. You can try using [M5Tool](https://github.com/m5stack/M5Tools) to upgrade the screen firmware to resolve this issue.

## Features

- ESP32-D0WDQ6-V3 Core:
  - 16MB Flash
  - 8MB PSRAM
  - 2.4 GHz Wi-Fi
- Human-Machine Interaction
  - 2.0" Color Capacitive Touchscreen
  - Built-in Speaker
  - Vibration Motor
- Standalone Peripheral Expansion Board
  - BMI270 6-Axis IMU
  - PDM Microphone
- AXP192 Power Management
- RTC Clock
- Built-in 500mAh Lithium Battery
- HY2.0-4P Expansion Interface
- microSD Card Slot
- Development Platforms
  - UiFlow1
  - UiFlow2
  - Arduino IDE
  - ESP-IDF
  - PlatformIO

## Includes

- 1 x Core2 v1.3
- 1 x USB Type-C Cable (20cm)
- 1 x Hex Key L-Shape 2.0mm (For M2.5 Screw)

## Applications

- IoT Controller
- DIY Projects
- Smart Home Devices

## Specifications

| Specification                   | Parameter                                                                                                                    |
| ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| SoC                             | ESP32-D0WDQ6-V3 @ Xtensa® 32-bit LX6 dual-core processor, clock frequency 240MHz                                             |
| Flash                           | 16MB                                                                                                                         |
| PSRAM                           | 8MB                                                                                                                          |
| Wi-Fi                           | 2.4 GHz Wi-Fi                                                                                                                |
| Input Voltage                   | 5V @ 500mA                                                                                                                   |
| Host Interface                  | USB Type-C x 1, GROVE (I2C+I/O+UART) x 1                                                                                     |
| LED                             | Green Power Indicator                                                                                                        |
| Buttons                         | Power Button, RST Button, Screen Virtual Buttons x 3                                                                         |
| Vibration Alert                 | Vibration Motor                                                                                                              |
| IPS LCD Screen                  | 2.0"@320 x 240 ILI9342C                                                                                                      |
| Capacitive Touch IC             | FT6336U                                                                                                                      |
| Microphone                      | SPM1423                                                                                                                      |
| I2S Amplifier                   | NS4168                                                                                                                       |
| IMU                             | BMI270                                                                                                                       |
| RTC                             | BM8563                                                                                                                       |
| PMU                             | AXP192                                                                                                                       |
| USB-TTL                         | CH9102F                                                                                                                      |
| Lithium Battery                 | 3.7V @ 500mAh                                                                                                                |
| RTC Battery                     | MS412FE 3V 1.0mAh Rechargeable Micro Lithium Battery                                                                         |
| Charging Parameters             | Charging Current: 0.219A<br/>Current After Full Charge (Power Off): 0.055A<br/>Current When Fully Charged (Power On): 0.147A |
| Antenna                         | 2.4G 3D Antenna                                                                                                              |
| Operating Temperature           | 0 ~ 60°C                                                                                                                     |
| Base Screw Specification        | Hex Countersunk M3                                                                                                           |
| Internal PCB Reserved Interface | Battery Interface (Spec: 1.25mm-2P), USB Line Interface (Spec: 1.25mm-4P)                                                    |
| Product Size                    | 54.0 x 54.0 x 16.5mm                                                                                                         |
| Product Weight                  | 58.8g                                                                                                                        |
| Package Size                    | 80.0 x 59.9 x 21.6mm                                                                                                         |
| Gross Weight                    | 88.2g                                                                                                                        |

## Learn

### Power On/Off

- Power On: Single-click the left power button
- Power Off: Long-press the left power button
- Reset: Single-click the RST button on the bottom

<img src="https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/1231/Core2_v1.3_operate.gif" width="40%">

### Onboard Reserved Interface

The PCB of Core2 v1.3 is reserved with a USB-TTL chip interface and a lithium battery interface.

<img src="https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/1231/ext-port-pin.png" width="40%">

### IMU Triaxial Direction Schematic Diagram

<img src="https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/1231/IMU-Core2-v1.3.jpg" width="70%">

## Certifications

- CE/MIC/FCC/RCM
- IEC62133

## Schematics

- [Core2 v1.3 Core Section Schematics PDF](https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/644/CORE2_V1.0_SCH.pdf)
- [Core2 v1.3 Expansion Board Section Schematics PDF](https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/486/core2_v1.3_SCH_2025_11_14_09_40_33.pdf)

<SchViewer>
<img src="https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/644/CORE2_V1.0_SCH_page_01.png" width="80%">
<img src="https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/486/core2_v1.3_SCH_2025_11_14_09_40_33_page_01.png" width="80%">
</SchViewer>

## PinMap

### LCD

| ESP32-D0WDQ6-V3 | G38  | G23  | G18 | G5  | G15 |
| --------------- | ---- | ---- | --- | --- | --- |
| ILI9342C        | MISO | MOSI | SCK | CS  | DC  |

| AXP192   | AXP_IO4 | AXP_DC3 | AXP_LDO2 |
| -------- | ------- | ------- | -------- |
| ILI9342C | RST     | BL      | PWR      |

### microSD

| ESP32-D0WDQ6-V3 | G38  | G23  | G18 | G4  |
| --------------- | ---- | ---- | --- | --- |
| microSD         | MISO | MOSI | SCK | CS  |

### Touch

| ESP32-D0WDQ6-V3 | G21 | G22 | G39 |
| --------------- | --- | --- | --- |
| FT6336U (0x38)  | SDA | SCL | INT |

| AXP192  | AXP_IO4 |
| ------- | ------- |
| FT6336U | RST     |

### Audio

| ESP32-D0WDQ6-V3 | G12  | G0   | G2   | G34  |
| --------------- | ---- | ---- | ---- | ---- |
| NS4168          | BCLK | LRCK | DATA |      |
| SPM1423         |      | CLK  |      | DATA |

| AXP192 | AXP_IO2 |
| ------ | ------- |
| NS4168 | SPK_EN  |

### AXP Power Indicator & Vibration Motor

| AXP192          | AXP_IO1 | AXP_LDO3 |
| --------------- | ------- | -------- |
| Green LED       | VCC     |          |
| Vibration Motor |         | VCC      |

### RTC

| ESP32-D0WDQ6-V3 | G21 | G22 |
| --------------- | --- | --- |
| BM8563 (0x51)   | SDA | SCL |

| AXP192 | AXP_PWR |
| ------ | ------- |
| BM8563 | INT     |

### IMU (3-Axis Gyroscope + 3-Axis Accelerometer)

| ESP32-D0WDQ6-V3 | G21 | G22 |
| --------------- | --- | --- |
| BMI270 (0x68)   | SDA | SCL |

### Internal I2C Connections

| ESP32-D0WDQ6-V3 | G21 | G22 |
| --------------- | --- | --- |
| BMI270 (0x68)   | SDA | SCL |
| AXP192 (0x34)   | SDA | SCL |
| BM8563 (0x51)   | SDA | SCL |
| FT6336U (0x38)  | SDA | SCL |

### HY2.0-4P

::grove-table
| HY2.0-4P | Black | Red | Yellow | White |
| -------- | ----- | --- | ------ | ----- |
| PORT.A   | GND   | 5V  | G32    | G33   |
::

### M5-Bus

::m5-bus-table
| FUNC       | PIN | LEFT | RIGHT | PIN | FUNC       |
| ---------- | --- | ---- | ----- | --- | ---------- |
|            | GND | 1    | 2     | G35 | ADC        |
|            | GND | 3    | 4     | G36 | ADC        |
|            | GND | 5    | 6     | RST | EN         |
| MOSI       | G23 | 7    | 8     | G25 | DAC        |
| MISO       | G38 | 9    | 10    | G26 | DAC        |
| SCK        | G18 | 11   | 12    | 3V3 |            |
| RXD0       | G3  | 13   | 14    | G1  | TXD0       |
| RXD2       | G13 | 15   | 16    | G14 | TXD2       |
| Int SDA    | G21 | 17   | 18    | G22 | Int SCL    |
| PORT.A SDA | G32 | 19   | 20    | G33 | PORT.A SCL |
| GPIO       | G27 | 21   | 22    | G19 | GPIO       |
| I2S_DOUT   | G2  | 23   | 24    | G0  | I2S_LRCK   |
|            | NC  | 25   | 26    | G34 | I2S_DATA   |
|            | NC  | 27   | 28    | 5V  |            |
|            | NC  | 29   | 30    | BAT |            |
::

## Model Size

- [Core2 v1.3 Model Size PDF](https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/1231/K010-V13_Core2_v1.3_model-size.pdf)

<img src="https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/1231/K010-V13_Core2_v1.3_model-size_page_01.png" width="100%">

## Structure

- [Core2 v1.3 Structure Files](https://github.com/m5stack/M5_Hardware/tree/master/Products/K010-V13_Core2_v1.3/Structures)

## Datasheets

- [ESP32](https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/644/esp32_datasheet_en.pdf)
- [FT6336U](https://m5stack.oss-cn-shenzhen.aliyuncs.com/resource/docs/datasheet/core/Ft6336GU_Firmware%20%E5%A4%96%E9%83%A8%E5%AF%84%E5%AD%98%E5%99%A8_20151112.xlsx)
- [NS4168](https://m5stack.oss-cn-shenzhen.aliyuncs.com/resource/docs/datasheet/core/NS4168_CN_datasheet.pdf)
- [BMI270](https://m5stack.oss-cn-shenzhen.aliyuncs.com/resource/docs/datasheet/core/K128%20CoreS3/BMI270.PDF)
- [ILI9342C](https://m5stack.oss-cn-shenzhen.aliyuncs.com/resource/docs/datasheet/core/ILI9342C-ILITEK.pdf)
- [SPM1423](https://m5stack.oss-cn-shenzhen.aliyuncs.com/resource/docs/datasheet/core/SPM1423HM4H-B_datasheet_en.pdf)
- [BM8563](https://m5stack.oss-cn-shenzhen.aliyuncs.com/resource/docs/datasheet/core/BM8563_V1.1_cn.pdf)
- [SY7088](https://m5stack.oss-cn-shenzhen.aliyuncs.com/resource/docs/datasheet/core/SY7088-Silergy.pdf)
- [AXP192 Datasheet](https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/1231/AXP192_datasheet_en.pdf)
- [1027DC Motor](https://m5stack.oss-cn-shenzhen.aliyuncs.com/resource/docs/datasheet/core/1027RFN01-33d.pdf)

## Softwares

### Arduino

- [Core2 v1.3 Arduino Quick Start](/en/arduino/m5core2/program)
- [Core2 v1.3 Arduino Library](https://github.com/m5stack/M5Core2)
- [Core2 v1.3 Arduino API](/en/arduino/m5core2/button)

<!--Note: links have been replaced-->

### UiFlow1

- [Core2 v1.3 UiFlow1 Quick Start](/en/uiflow/m5core2/program)

<!--Note: links have been replaced-->

### UiFlow2

- [Core2 v1.3 UiFlow2 Quick Start](/en/uiflow2/m5core2/program)

<!--Note: links have been replaced-->

### PlatformIO

```
[env:m5stack-core2]
platform = espressif32@6.12.0
board = m5stack-core2
framework = arduino
upload_speed = 921600
monitor_speed = 115200
board_build.partitions = default_16MB.csv
build_type = debug
build_flags =
    -DBOARD_HAS_PSRAM
    -DCORE_DEBUG_LEVEL=5
lib_deps =
    M5Unified=https://github.com/m5stack/M5Unified
```

### ESP-IDF

- [Core2 v1.3 ESP-IDF BSP Guide](/en/esp_idf/m5core2/bsp)

<!--Note: links have been replaced-->

### USB Driver

Download and install the **CH9102** USB serial (VCP) driver from the table below according to your operating system. When installing **CH9102_VCP_SER_MacOS v1.7**, the installer may display an error message, which is typically a false positive — the driver is usually installed correctly and you can safely dismiss the prompt and proceed. If firmware flashing or downloading fails, times out, or returns errors such as `Failed to write to target RAM`, try reinstalling the driver or switching to a different USB cable or port.

| Driver Name               | Compatible Chip | Download                                                                                             |
| ------------------------- | --------------- | ---------------------------------------------------------------------------------------------------- |
| CH9102_VCP_SER_Windows    | CH9102          | [Download](https://m5stack.oss-cn-shenzhen.aliyuncs.com/resource/drivers/CH9102_VCP_SER_Windows.exe) |
| CH9102_VCP_SER_MacOS v1.7 | CH9102          | [Download](https://m5stack.oss-cn-shenzhen.aliyuncs.com/resource/drivers/CH9102_VCP_MacOS_v1.7.zip)  |

### Easyloader

| Easyloader             | Download                                                                                     | Note |
| ---------------------- | -------------------------------------------------------------------------------------------- | ---- |
| Core2 Factory Firmware | [Download](https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/1231/Core2_Factory_FirmWare.exe) | /    |

### Other

- [ESP32 Formats and Communication Protocols](https://link.springer.com/book/10.1007/978-1-4842-9376-8)

<img src="https://m5stack.oss-cn-shenzhen.aliyuncs.com/resource/docs/products/core/core2/07c3be99c38835c886b7afc23c10083.jpg" width="80%">

> [_ESP32 Formats and Communication Protocols_](https://link.springer.com/book/10.1007/978-1-4842-9376-8) dedicates several chapters to the M5Stack Core2 module. The M5Stack Core2 integrates a touch LCD screen with Wi-Fi connectivity, a microphone and speaker, as well as an accelerometer and gyroscope, making it an exceptionally versatile platform. The book uses communication protocols to build a variety of projects — ranging from connecting a smartwatch to a smartphone (BLE) and long-range communication with satellites orbiting Earth (LoRa), to audio signal transmission between devices (I2S). It also covers the use of QR codes for controlling external devices over the internet, as well as ESP-MESH and ESP-NOW protocols for enabling communication between microcontrollers without an internet connection.

## Video

<VideoGallery>
  <VideoItem title="Core2 v1.3 Product Introduction and Feature Demonstration" url="https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/1231/K010-V13-Core2-v1.3-video-EN.mp4" />
</VideoGallery>

## Product Comparison

::compare-table
| Product Compare       | [Core2 v1.3](/en/core/Core2_v1.3) ![Core2 v1.3](https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/1231/K010-V13-Core2-v1.3-main-pictures_02.webp) | [Core2 v1.1](/en/core/Core2%20v1.1) ![Core2 v1.1](https://static-cdn.m5stack.com/resource/docs/products/core/Core2%20v1.1/img-9eb726ec-5729-42c3-9cce-e06140856095.webp) | [Core2](/en/core/core2) ![Core2](https://static-cdn.m5stack.com/resource/docs/products/core/core2/core2_cover_01.webp) |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------- |
| IMU                   | BMI270                                                                                                                                           | MPU6886                                                                                                                                                                  | MPU6886                                                                                                                |
| PMIC                  | AXP192                                                                                                                                           | AXP2101                                                                                                                                                                  | AXP192                                                                                                                 |
| USB-TTL               | CH9102                                                                                                                                           | CH9102                                                                                                                                                                   | CP2104/CH9102                                                                                                          |
| Power Indicator Color | Green                                                                                                                                            | Blue                                                                                                                                                                     | Green                                                                                                                  |
::

To compare products across the controller series, visit the [Product Selection Table](/en/products_selector/m5core_compare?select=K010-V13) and select the target products to view a side-by-side comparison. The table covers key parameters and feature highlights, supporting simultaneous comparison of multiple products.
