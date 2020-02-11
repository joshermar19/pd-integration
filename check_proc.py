import requests
import socket
import json
import time
import os

INTERVAL = 300  # SECONDS! Use something slightly more sane for production!
PD_URL = 'https://events.pagerduty.com/v2/enqueue'
HOST = socket.getfqdn()  # Were this to change, it would require the script be restarted

PROC_NAME = os.environ['PROC_NAME']
INT_KEY = os.environ['INT_KEY']


def check_proc_running(process_name):
    # Remember, we are using the "exit code/return status", not the stdout from this cmd.
    # The inversion is done because 0 means "success", and 1 means no process found.
    return not os.system(f'pgrep {process_name} &> /dev/null')


def trigger(dedup_key):
    payload = {
        "event_action": "trigger",
        "routing_key": INT_KEY,
        "payload": {
            "severity": "critical",
            "source": HOST,
            "summary": f"[TEST] {PROC_NAME} has stopped running on {HOST}",
            "custom_details": {
                "Info": (
                    f"{PROC_NAME} has stopped running on {HOST} within the last {INTERVAL} seconds. "
                    "Please reach out to service owner for troubleshooting.")
            }
        }
    }

    if dedup_key:  # If not, that means this is the first trigger
        payload["dedup_key"] = dedup_key

    try:
        response = requests.post(PD_URL, data=json.dumps(payload))
        print(response.status_code)
        print(response.text)
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
        print(response.status_code)
        print(response.text)
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

        print()  # Space is the essence of Zen...

        time.sleep(INTERVAL)


if __name__ == '__main__':
    main()
