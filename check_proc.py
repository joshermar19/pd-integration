import subprocess
import requests
import socket
import json
import time
import os

INTERVAL = 300  # SECONDS
PD_URL = 'https://events.pagerduty.com/v2/enqueue'
HOST = socket.getfqdn()  # Were this to change, it would require the script be restarted

PROC_NAME = os.environ['PROC_NAME']
INT_KEY = os.environ['INT_KEY']


def check_proc_running(proc_name):
    stdout = subprocess.run(['pgrep', proc_name], stdout=subprocess.PIPE).stdout

    if stdout:
        pids_list = stdout.decode('utf-8').strip().split('\n')
        print(f'Found {proc_name} with PIDs: ' + ''.join(pids_list))
    else:
        print(f'No running PIDs found for {proc_name}')

    return bool(stdout)  # Simple enough. Empty string means its not running.


def trigger(dedup_key):
    payload = {
        "event_action": "trigger",
        "routing_key": INT_KEY,
        "payload": {
            "severity": "critical",
            "source": HOST,
            "summary": f"{PROC_NAME} has stopped running on {HOST}",
            "custom_details": {
                "info": (
                    f"{PROC_NAME} was not running on {HOST} within the last {INTERVAL} seconds. "
                    "Please reach out to service owner for troubleshooting.")
            }
        }
    }

    if dedup_key:  # If not, this is the first trigger and this should not be added to payload
        payload["dedup_key"] = dedup_key

    try:
        response = requests.post(PD_URL, data=json.dumps(payload))
        print(response.status_code, response.text)
        return response.json()["dedup_key"]

    except requests.exceptions.RequestException as e:
        print(e, 'Unable to trigger incident!')
        return None


def resolve(dedup_key):
    payload = {
        "event_action": "resolve",
        "routing_key": INT_KEY,
        "dedup_key": dedup_key
    }

    try:
        response = requests.post(PD_URL, data=json.dumps(payload))
        print(response.status_code, response.text)
        return True

    except requests.exceptions.RequestException as e:
        print(e, 'Unable to resolve incident!')
        return False


def main():
    dedup_key = None  # This also keeps track of whether or not the incident has triggered successfully

    while True:
        running = check_proc_running(PROC_NAME)

        # If it's NOT running, keep triggering EVERY time
        if not running:
            print(f'{PROC_NAME} is NOT running. Triggering/Retriggering incident.')

            # None here would mean that there was a connection problem
            new_dedup = trigger(dedup_key)

            # A new dedup also means a successful request
            if new_dedup:
                dedup_key = new_dedup

        # Presence of dedup key means that it was triggerred and has not yet been resolved
        elif dedup_key:
            print(f'{PROC_NAME} is running again. Resolving incident.')

            resolved = resolve(dedup_key)

            # This is important because if it is not able to resolve, try again next time around
            if resolved:
                dedup_key = None

        else:
            print(f'{PROC_NAME} appears to be running and incident is untriggered.')

        print(f'Checking again in {INTERVAL} seconds...')

        time.sleep(INTERVAL)


if __name__ == '__main__':
    main()
