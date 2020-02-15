from apscheduler.schedulers.blocking import BlockingScheduler
from pytz import timezone
import subprocess
import requests
import socket
import json
import os

INTERVAL = 300  # SECONDS
PD_URL = 'https://events.pagerduty.com/v2/enqueue'
HOST = socket.getfqdn()  # Were this to change, it would require the script be restarted
TZ = timezone('America/Los_Angeles')

PROC_NAME = os.environ['PROC_NAME']
INT_KEY = os.environ['INT_KEY']

dedup_key = None  # This also keeps track of whether or not an incident was triggered successfully


def monitor_tester():
    trigg_payload = {
        "event_action": "trigger",
        "routing_key": INT_KEY,
        "payload": {
            "severity": "info",
            "source": HOST,
            "summary": f"[INTEGRATION TEST] process monitor for {PROC_NAME} on {HOST}",  # MAKE ME AN f-string!
            "custom_details": {
                "info": (
                    f"This is an integration test for the monitoring of {PROC_NAME} on {HOST}. "  # MAKE ME AN f-string!
                    "It will trigger once when the integration comes online and subsequently "
                    "every first day of the month at 17:00.")
            }
        }
    }

    try:
        response = requests.post(PD_URL, data=json.dumps(trigg_payload))
        dedup_key = response.json()["dedup_key"]
        print(response.status_code, f'Trigerred INTEGRATION TEST {dedup_key}')

    except requests.exceptions.RequestException as e:
        print(e, 'Unable to trigger check!')
        return  # No point in continuing if this is the case

    ack_payload = {
        "event_action": "acknowledge",
        "routing_key": INT_KEY,
        "dedup_key": dedup_key
    }

    try:
        response = requests.post(PD_URL, data=json.dumps(ack_payload))
        print(response.status_code, f'Acknowledged {dedup_key}')

    except requests.exceptions.RequestException as e:
        print(e, 'Unable to ack check!')

    print()  # Space is the essence of Zen


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

    if dedup_key:  # If not, this is the first trigger and no dedup_key should be sent
        payload["dedup_key"] = dedup_key

    try:
        response = requests.post(PD_URL, data=json.dumps(payload))
        current_dedup = response.json()["dedup_key"]
        print(response.status_code, f'Triggered/retriggered with {current_dedup}')
        return current_dedup

    except requests.exceptions.RequestException as e:
        print(e, 'Unable to trigger/retrigger incident!')
        return None


def resolve(dedup_key):
    payload = {
        "event_action": "resolve",
        "routing_key": INT_KEY,
        "dedup_key": dedup_key
    }

    try:
        response = requests.post(PD_URL, data=json.dumps(payload))
        print(response.status_code, f'Resolved {dedup_key}')
        return True

    except requests.exceptions.RequestException as e:
        print(e, 'Unable to resolve incident!')
        return False


def check_proc_running(proc_name):
    stdout = subprocess.run(['pgrep', proc_name], stdout=subprocess.PIPE).stdout

    if stdout:
        pids_list = stdout.decode('utf-8').strip().split('\n')
        print(f'Found {proc_name} with PID(s): ' + ', '.join(pids_list))
    else:
        print(f'No PIDs found for {proc_name}')

    return bool(stdout)  # Simple enough. Empty string means its not running.


def monitor():
    global dedup_key

    running = check_proc_running(PROC_NAME)

    # If it's NOT running, go ahead and trigger/retrigger
    if not running:
        print(f'{PROC_NAME} is NOT running. Attempting trigger/retrigger...')

        new_dedup = trigger(dedup_key)

        # If a new dedup is provided, that's the "current dedup"
        dedup_key = new_dedup or dedup_key

    # If it is running and dedup_key is set, that means it needs to be resolved
    elif dedup_key:
        print(f'{PROC_NAME} is running again. Attempting to resolve incident...')

        resolved = resolve(dedup_key)

        # If not able to resolve (connection err), try again next time around
        if resolved:
            dedup_key = None

    else:
        print(f'{PROC_NAME} appears to be running and incident is untriggered')

    print(f'Checking again in {INTERVAL} seconds.\n')


def scheduler():
    sched = BlockingScheduler()

    sched.add_job(monitor_tester, 'cron', day='01', hour='17', timezone=TZ)
    sched.add_job(monitor, 'interval', seconds=INTERVAL)

    print('Starting scheduler')
    sched.start()


if __name__ == '__main__':
    try:
        monitor_tester()  # Initial "gauge sweep"
        scheduler()
    except KeyboardInterrupt:
        print("Ending Scheduler")
