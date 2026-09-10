#!/usr/bin/env python3
"""MQTT listener for Home Assistant integration debugging - with wildcard subscription."""

import paho.mqtt.client as mqtt
import json
import time

# MQTT configuration from .env
BROKER = "192.168.1.12"
PORT = 1883
USERNAME = "kzuca"
PASSWORD = "123"

# Option 1: Subscribe to ALL topics (wildcard) - best for discovery
# Option 2: Specific topics (comment out wildcard line below)
TOPICS = [("tucuxi/#", 1)]  # Wildcard: catches ALL MQTT topics

# Specific topics (uncomment if you want only specific topics):
# TOPICS = [
#     ("tucuxi/mode/alarme/set", 1),          # Alarm switch command
#     ("tucuxi/mode/alarme/state", 1),        # Alarm switch state
#     ("tucuxi/ha/alarm_mode", 1),            # Alarm mode sensor
#     ("tucuxi/mode/viagem/set", 1),          # Viagem switch command
#     ("tucuxi/mode/viagem/state", 1),        # Viagem switch state
#     ("tucuxi/predictions/rosa", 1),         # Predictor rosa
#     ("tucuxi/predictions/portao_entrada", 1),  # Predictor portão
# ]

def on_connect(client, userdata, flags, rc):
    print(f"Connected with result code {rc}")
    if rc == 0:
        print("Connected to MQTT broker!")
        # Subscribe to topics
        for topic, qos in TOPICS:
            client.subscribe(topic, qos)
            print(f"Subscribed to {topic}")
    else:
        print(f"Failed to connect, return code {rc}")

def on_message(client, userdata, msg):
    """Called when a message is received on any subscribed topic."""
    try:
        payload = msg.payload.decode()
        topic = msg.topic
        
        # Try to parse as JSON
        data = None
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            pass
        
        # Print formatted output
        print(f"\n{'='*60}")
        print(f"TOPIC: {topic}")
        if data is not None:
            print(f"PAYLOAD: {json.dumps(data, indent=2)}")
        else:
            print(f"PAYLOAD: {payload}")
        print(f"{'='*60}")
        
        # Handle common patterns
        if data is not None:
            # Alarm mode
            if "alarm_mode" in data:
                mode = data.get("alarm_mode", "")
                mode_map = {
                    "armed_home": "🟢 ARMED_HOME",
                    "armed_away": "🔴 ARMED_AWAY", 
                    "disarmed": "🟡 DISARMED"
                }
                print(f"Alarm Mode: {mode_map.get(mode, mode)}")
            
            # Switch states
            if "ON" in str(data) or "OFF" in str(data):
                switch = "ON" if "ON" in str(data) else "OFF" 
                print(f"Alarm Switch: {switch}")
            
            # Predictor probabilities
            if "probabilidade" in data:
                prob = data.get("probabilidade", 0)
                print(f"Probability: {prob}%")
        
        # Handle plain string payloads
        if data is None and ("ON" in payload or "OFF" in payload or "armed_" in payload.lower() or "disarmed" in payload.lower()):
            payload_lower = payload.lower()
            if "armed_home" in payload_lower or "armed_away" in payload_lower:
                print(f"Alarm Mode (plain): {payload.strip()}")
            elif "disarmed" in payload_lower:
                print(f"Alarm Mode (plain): {payload.strip()}")
            elif "ON" in payload:
                print(f"Alarm Switch (plain): ON")
            elif "OFF" in payload:
                print(f"Alarm Switch (plain): OFF")
                
    except Exception as e:
        print(f"Error processing message: {e}\n{topic}: {payload}")

def main():
    client = mqtt.Client()
    if USERNAME and PASSWORD:
        client.username_pw_set(USERNAME, PASSWORD)
    
    client.on_connect = on_connect
    client.on_message = on_message
    
    print(f"Connecting to MQTT broker at {BROKER}:{PORT}...")
    client.connect_async(BROKER, PORT, keepalive=60)
    client.loop_start()
    
    print("Listening for MQTT messages... (Press CTRL+C to stop)")
    print(f"Subscribed to: {[t[0] for t in TOPICS]}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
        client.loop_stop()
        client.disconnect()
        print("Disconnected.")

if __name__ == "__main__":
    main()