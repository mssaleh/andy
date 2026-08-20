# StickC-Plus

<span class="product-sku">SKU:K016-P</span>

<PictureViewer>
<img src="https://static-cdn.m5stack.com/resource/docs/products/core/m5stickc_plus/m5stickc_plus_01.webp">
<img src="https://static-cdn.m5stack.com/resource/docs/products/core/m5stickc_plus/m5stickc_plus_02.webp">
<img src="https://static-cdn.m5stack.com/resource/docs/products/core/m5stickc_plus/m5stickc_plus_03.webp">
<img src="https://static-cdn.m5stack.com/resource/docs/products/core/m5stickc_plus/m5stickc_plus_04.webp">
<img src="https://static-cdn.m5stack.com/resource/docs/products/core/m5stickc_plus/m5stickc_plus_05.webp">
<img src="https://static-cdn.m5stack.com/resource/docs/products/core/m5stickc_plus/m5stickc_plus_06.webp">
<img src="https://static-cdn.m5stack.com/resource/docs/products/core/m5stickc_plus/m5stickc_plus_07.webp">
<img src="https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/669/K016-P_02.jpg">
</PictureViewer>

## Description

**StickC-Plus** is the large-screen version of the [M5StickC](/en/core/m5stickc). Its main controller uses the ESP32-PICO-D4 module, which supports Wi-Fi. Inside its compact body, it integrates rich hardware resources such as infrared, RTC, microphone, LED, IMU, buttons, buzzer, PMU, and more. While retaining the original functions of the M5StickC, it adds a passive buzzer. Additionally, the screen size has been upgraded to 1.14 inches, with a resolution of 135 x 240 TFT, increasing the display area by 18.7% compared to the previous 0.96-inch screen. The battery capacity is 120mAh, and the interface supports HAT and Unit series products.

This compact and exquisite development tool can unleash unlimited creative potential. StickC-Plus can help quickly build IoT product prototypes, greatly simplifying the entire development process. Even for beginners who are just starting to learn programming, it can be used to create interesting applications and apply them to real-life scenarios.

## Tutorial

learn>| ![UIFlow](https://m5stack.oss-cn-shenzhen.aliyuncs.com/resource/docs/static/assets/img/uiflow/uiflow1.0_banner_01.png) | [UIFlow](/en/uiflow/m5stickc_plus/program) | This tutorial will introduce how to control the StickC-Plus device through the UIFlow graphical programming platform. |

learn>| ![UiFlow2](https://m5stack.oss-cn-shenzhen.aliyuncs.com/resource/docs/static/assets/img/uiflow2/uiflow2.0_banner_01.png) | [UiFlow2](/en/uiflow2/m5stickcplus/program) | This tutorial will introduce how to control the StickC-Plus device through the UiFlow2 graphical programming platform. |

learn>| ![Arduino IDE](https://m5stack.oss-cn-shenzhen.aliyuncs.com/resource/docs/static/assets/img/arduino/arduino_banner_01.png) | [Arduino IDE](/en/arduino/m5stickc_plus/program) | This tutorial will introduce how to program and control the StickC-Plus device using the Arduino IDE. |

## Features

- Based on ESP32 development, supports Wi-Fi
- Built-in 3-axis accelerometer and 3-axis gyroscope
- Built-in Red LED
- Integrated infrared transmitter
- Built-in RTC
- Integrated microphone
- User button, LCD (1.14 inch), power/reset button
- 120 mAh lithium battery
- Expansion interface
- Integrated passive buzzer
- Wearable & mountable
- Development Platform
  - UiFlow1
  - UiFlow2
  - Arduino IDE
  - ESP-IDF
  - PlatformIO

## Includes

- 1 x StickC-Plus

## Applications

- Wearable devices
- IoT controllers
- STEM education
- DIY projects
- Smart home devices

## Specifications

| Specifications        | Parameter                                                                           |
| --------------------- | ----------------------------------------------------------------------------------- |
| SoC                   | ESP32-PICO-D4 @ Xtensa® 32-bit LX6 dual-core processor, clock frequency up to 240MHz |
| Flash                 | 4MB                                                                                 |
| Wi-Fi                 | 2.4 GHz Wi-Fi                                                                       |
| DMIPS                 | 600                                                                                 |
| SRAM                  | 520KB                                                                               |
| Input Voltage         | 5V@500mA                                                                            |
| Interface             | USB Type-C x 1, GROVE (I2C+I/O+UART) x 1                                            |
| LCD Screen            | 1.14 inch, 135 x 240 Colorful TFT LCD, ST7789v2                                     |
| Microphone            | SPM1423                                                                             |
| Button                | Custom Button x 2                                                                   |
| LED                   | Red LED x 1                                                                         |
| RTC                   | BM8563                                                                              |
| PMU                   | AXP192                                                                              |
| Buzzer                | Onboard Buzzer                                                                      |
| IR                    | Infrared Transmission                                                               |
| MEMS                  | MPU6886                                                                             |
| Antenna               | 2.4G 3D Antenna                                                                     |
| External Pins         | G0, G25/G26, G36, G32, G33                                                          |
| Battery               | 120mAh@3.7V, inside vb                                                              |
| Operating Temperature | 0 ~ 60°C                                                                            |
| Shell Material        | Plastic (PC)                                                                        |
| Product Size          | 48.0 x 24.0 x 13.5mm                                                                |
| Product Weight        | 16.9g                                                                               |
| Package Size          | 104.4 x 65.0 x 18.0mm                                                               |
| Gross Weight          | 24.1g                                                                               |

## Learn

### Power On/Off Operations

- Power On / Reset: Press the power button once
- Power Off: Press and hold the power button

### IMU Triaxial Direction Schematic Diagram

<img src="https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/669/IMU-StickC-Plus.jpg" width="70%">

## Schematics

- [StickC-Plus Schematic PDF](https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/669/k016-p-StickC-Plus-sche.pdf)

<img src="https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/669/SCH_StickC_Plus_page_01.png" width="100%">

## PinMap

### Red LED & IR Transmitter & Button & Buzzer

| ESP32-PICO-D4  | G10     | G9     | G37        | G39        | G2         |
| -------------- | ------- | ------ | ---------- | ---------- | ---------- |
| Red LED        | LED Pin |        |            |            |            |
| IR Transmitter |         | IR Pin |            |            |            |
| Button A       |         |        | Button Pin |            |            |
| Button B       |         |        |            | Button Pin |            |
| Passive Buzzer |         |        |            |            | Buzzer Pin |

### Color TFT Screen

Driver Chip: ST7789v2

Resolution: 135 x 240

| ESP32-PICO-D4 | G15      | G13     | G23    | G18     | G5     |
| ------------- | -------- | ------- | ------ | ------- | ------ |
| TFT Screen    | TFT_MOSI | TFT_CLK | TFT_DC | TFT_RST | TFT_CS |

### Microphone MIC (SPM1423)

| ESP32-PICO-D4  | G0  | G34  |
| -------------- | --- | ---- |
| Microphone MIC | CLK | DATA |

### 6-Axis IMU (MPU6886) & Power Management Chip (AXP192)

| ESP32-PICO-D4         | G22 | G21 |
| --------------------- | --- | --- |
| 6-Axis IMU            | SCL | SDA |
| Power Management Chip | SCL | SDA |

### Power Management Chip (AXP192)

| Microphone | RTC  | TFT Backlight | TFT IC | ESP32/3.3V MPU6886 | 5V GROVE |
| ---------- | ---- | ------------- | ------ | ------------------ | -------- |
| LDOio0     | LDO1 | LDO2          | LDO3   | DC-DC1             | IPSOUT   |

### Power Switch

| APX192       | PWRON   |
| ------------ | ------- |
| Power Switch | pwr_key |

### HY2.0-4P

::grove-table
| HY2.0-4P    | Black | Red | Yellow | White |
| ----------- | ----- | --- | ------ | ----- |
| PORT.CUSTOM | GND   | 5V  | G32    | G33   |
::

**Power Structure Diagram**

<img src="https://static-cdn.m5stack.com/resource/docs/products/core/m5stickc_plus/m5stickc_plus_sch_01.webp" width="20%">
<img src="https://static-cdn.m5stack.com/resource/docs/products/core/m5stickc_plus/m5stickc_plus_sch_02.webp" width="20%">

## Model Size

<img alt="module size" src="https://m5stack.oss-cn-shenzhen.aliyuncs.com/resource/docs/products/core/m5stickc_plus/%E5%B0%BA%E5%AF%B8%E5%9B%BE.jpg" width="100%" />

## Structure

- [StickC-Plus Structure Files](https://github.com/m5stack/M5_Hardware/tree/master/Products/K016-P_StickC-Plus/Structures)

## Datasheets

- [ESP32-PICO](https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/669/esp32-pico_series_datasheet_en.pdf)
- [ST7789v2](https://m5stack.oss-cn-shenzhen.aliyuncs.com/resource/docs/datasheet/core/ST7789V.pdf)
- [BM8563](https://m5stack.oss-cn-shenzhen.aliyuncs.com/resource/docs/datasheet/core/BM8563_V1.1_cn.pdf)
- [MPU6886](https://m5stack.oss-cn-shenzhen.aliyuncs.com/resource/docs/datasheet/core/MPU-6886-000193%2Bv1.1_GHIC_en.pdf)
- [AXP192 Datasheet](https://m5stack.oss-cn-shenzhen.aliyuncs.com/resource/docs/datasheet/core/AXP192_datasheet_en.pdf)
- [AXP192 Register](https://m5stack.oss-cn-shenzhen.aliyuncs.com/resource/docs/datasheet/core/AXP192_datasheet_en.pdf)
- [SPM1423](https://m5stack.oss-cn-shenzhen.aliyuncs.com/resource/docs/datasheet/core/SPM1423HM4H-B_datasheet_en.pdf)

## Softwares

### Arduino

- [StickC-Plus Arduino Quick Start](/en/arduino/m5stickc_plus/program)
- [StickC-Plus Arduino Driver Library](https://github.com/m5stack/M5StickC-Plus)
- [StickC-Plus Factory Test Example](https://github.com/m5stack/M5StickC-Plus/tree/master/examples/FactoryTest)

### UiFlow1

- [StickC-Plus UiFlow1 Quick Start](/en/uiflow/m5stickc_plus/program)

### UiFlow2

- [StickC-Plus UiFlow2 Quick Start](/en/uiflow2/m5stickcplus/program)

### USB Driver

?> Baud Rate Limitation | When downloading programs to the device, it is recommended to select one of the following serial baud rates. Using other speeds may cause the program to fail to download correctly. **1500000 bps** / **750000 bps** / **500000 bps** / **250000 bps** / **115200 bps**

Connect the device to the PC and install the [FTDI driver](https://ftdichip.com/drivers/vcp-drivers/) via Device Manager. Taking Windows 10 as an example, download the driver that matches your operating system, unzip it, and install it through Device Manager. (Note: In certain system environments, the driver needs to be installed twice before it becomes effective. Unrecognized device names are usually **M5Stack** or **USB Serial**. On Windows, it is recommended to install directly through Device Manager (custom update) using the driver files; the executable installer may not work properly). [Click here to download the FTDI driver](https://ftdichip.com/drivers/vcp-drivers/)

<div class="product_pic"><img src="https://static-cdn.m5stack.com/resource/docs/products/core/m5stickc/ftdi_01.webp"><img src="https://static-cdn.m5stack.com/resource/docs/products/core/m5stickc/ftdi_02.webp"><img src="https://static-cdn.m5stack.com/resource/docs/products/core/m5stickc/ftdi_03.webp"></div>

### Others

- [StickC-Plus Restore Factory Firmware Guide](/en/guide/restore_factory/m5stickc_plus)

**Note:**

- StickC-Plus supported baud rates: 1200 ~115200, 250K, 500K, 750K, 1500K

- G36/G25 share the same port. When using one pin, set the other pin to floating input.

  - For example, to use the G36 pin as an ADC input, configure the G25 pin as floating.

- The input range of VBUS_VIN and VBUS_USB is limited to 4.8-5.5V. When powered by VBUS, the AXP192 power management will charge the internal battery.

```cpp
setup()
{
   M5.begin();
   pinMode(36, INPUT);
   gpio_pulldown_dis(GPIO_NUM_25);
   gpio_pullup_dis(GPIO_NUM_25);
}
```

### Easyloader

| Easyloader                      | Download Link                                                                                                             | Remarks |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------- | ------- |
| StickC-Plus Firmware Easyloader | [download](https://m5stack.oss-cn-shenzhen.aliyuncs.com/EasyLoader/Windows/CORE/EasyLoader_M5StickC_Plus_FactoryTest.exe) | /       |

## Video

<VideoGallery>
  <VideoItem title="Accelerometer, microphone, LED, IR, RTC, wireless connection, and other hardware tests. Click button A or B to switch test items." url="https://m5stack.oss-cn-shenzhen.aliyuncs.com/video/Product_example_video/Core/M5StickC%20Plus.mp4" />
  <VideoItem title="Create a charging controller system" url="https://m5stack.oss-cn-shenzhen.aliyuncs.com/resource/docs/products/core/m5stickc_plus/ESP32%20Li-ion%20Battery%20Charger-ch.mp4" />
  <VideoItem title="StickC-Plus UiFlow2 Quick Start" bilibili="https://www.bilibili.com/video/BV17n4y197jg" youtube="https://www.youtube.com/watch?v=mcZHoT0x6UE" />
</VideoGallery>

## Product Comparison

To compare information on the Stick series products, you can visit the [Product Selection Table](/en/products_selector/m5stick_compare?select=K016-P), check the target products, and get the comparison results. The selection table covers key information such as core parameters and functional features, and supports comparison of multiple products simultaneously.

## Version Change

| Release Date | Product Changes                                            |
| ------------ | ---------------------------------------------------------- |
| 2021.12      | Added sleep and wake-up functions; version changed to v1.1 |
| /            | First release                                              |

