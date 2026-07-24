# Home Assistant Integration Guide

`smtp2mqtt` integrates smoothly with Home Assistant via MQTT.

## 1. Manual Binary Sensor Configuration

Add the following to your Home Assistant `configuration.yaml`:

```yaml
mqtt:
  binary_sensor:
    - name: "Driveway Camera Motion"
      unique_id: "smtp2mqtt_camera1_home_com"
      state_topic: "smtp2mqtt/camera1-home.com"
      payload_on: "ON"
      payload_off: "OFF"
      device_class: motion
```

## 2. Viewing Latest Camera Snapshot

You can display the latest image snapshot in Home Assistant using the Generic HTTP Camera integration:

```yaml
camera:
  - platform: generic
    name: "Driveway Camera Snapshot"
    still_image_url: "http://<SMTP2MQTT_IP>:8080/attachments/latest_camera1.jpg"
```
