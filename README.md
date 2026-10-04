**Event-Driven Smart Surveillance and Security Hub using ESP32-CAM and Multimodal AI**

**Project Overview**

The Event-Driven Smart Surveillance and Security Hub is an IoT and AI-based security system developed using ESP32-CAM and Python. The system provides real-time video streaming, object detection, unattended-object detection, hardware buzzer alerts, AI-based scene analysis, incident logging, and Telegram-based remote monitoring.

The ESP32-CAM captures and streams live video over Wi-Fi. The Python application processes the video using YOLO for detecting people and selected objects such as backpacks, handbags, suitcases, bottles, and mobile phones. When an object remains unattended for a specified period, the system generates an alert and records the incident.

**Features**

• Real-time ESP32-CAM video streaming

• YOLO-based object detection and tracking

• Unattended-object detection

• ESP32-CAM hardware buzzer alert

• Audio warning using text-to-speech

• Telegram security alerts

• Telegram remote commands

• AI-based image and scene analysis

• SQLite-based incident logging

• CSV incident report generation

• Remote arm/disarm functionality


**Hardware Components**

• ESP32-CAM

• PIR Sensor

• FTDI232 USB-to-Serial Adapter

• Active Buzzer

• Jumper Wires

• USB Cable

• Computer/Laptop

• Wi-Fi Network


**Software and Technologies**

• Arduino IDE

• Python

• Visual Studio Code

• OpenCV

• Ultralytics YOLO

• PyTorch

• SQLite

• Telegram Bot API

• Ollama

• Moondream

• pyttsx3


**Connections**

**FTDI232 to ESP32-CAM**

VCC ------>  5V

GND ------>  GND

RX  ------>  U0T

TX  ------>  U0R

**Buzzer to ESP32-CAM**

POSITIVE -----> GPIO 15

NEGATIVE -----> GND

The ESP32-CAM flash LED is connected to GPIO 4 and is configured to remain ON while the camera is operating.


**Working**

1. ESP32-CAM connects to the Wi-Fi network.

2. ESP32-CAM provides a live camera stream.

3. Python connects to the camera stream.

4. YOLO detects and tracks people and selected objects.

5. The system checks whether detected objects are near a person.

6. If an object remains unattended for the configured time, an alert is generated.

7. The system activates the audio warning.

8. The incident is stored in the SQLite database.

9. A Telegram alert is sent with the captured image and incident information.

10. The user can control and monitor the system through Telegram commands.



**Telegram Commands**

| `/status` | Get current camera and security status |

| `/history` | Get recent security incident history |

| `/buzzer` | Activate the hardware buzzer |

| `/arm` | Activate AI monitoring |

| `/disarm` | Pause AI monitoring |

The system can also receive normal text questions and use the local AI vision model to analyze the current camera image.


**AI Models**

**YOLO**

The project uses the Ultralytics YOLO model for real-time object detection and tracking.

Syntax:

model = YOLO("yolov8n.pt")


