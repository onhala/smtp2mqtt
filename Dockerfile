FROM alpine:3.12
WORKDIR /smtp2mqtt
COPY smtp2mqtt.py requirements.txt ./
RUN apk add --no-cache python3 py3-pip && pip3 install -r requirements.txt
EXPOSE 1025
CMD ["python3", "smtp2mqtt.py"]
