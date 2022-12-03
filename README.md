# smtp2mqtt

Receive emails and publish to MQTT. Super simple stuff. Topic will be `<configurable_prefix>/<sender_email.replace('@', '-')>`.

This is a modified version of wicol/emqtt. I use this for triggering of motion detection from my Hikvision cameras.
Available actions on the camera are to send an email or upload an image to an FTP or Hik Survailence Center.

This script makes it easier to integrate into automation systems - i use mqttgateway running on loxberry and reacting to the signals in Loxone.

Protip: `docker exec emqtt find attachments -type f -ctime +20 -delete`
## Run it in docker

```
$ docker build -t smtp2mqtt .
$ docker run -d \
    --name smtp2mqtt \
    --net host \
    --restart always \
    -e "MQTT_USERNAME=***SECRET***" \
    -e "MQTT_PASSWORD=***SECRET***" \
    -e "DEBUG=True" \
    -v /etc/localtime:/etc/localtime:ro \
    -v $PWD/log:/emqtt/log \
    -v $PWD/attachments:/emqtt/attachments \
    onhala/smtp2mqtt
```

