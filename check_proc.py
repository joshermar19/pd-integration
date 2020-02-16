from apscheduler.schedulers.blocking import BlockingScheduler
from pytz import timezone
import subprocess
import logging
import requests
import socket
import json
import os


HOST = socket.getfqdn()  # Were this to change suddenly, it would require the script be restarted
TZ = timezone('America/Los_Angeles')
PROC_NAME = os.environ['PROC_NAME']
INT_KEY = os.environ['INT_KEY']
PD_URL = 'https://events.pagerduty.com/v2/enqueue'

# The only configurable "setting". 5 minutes seems fine for now.
INTERVAL = 300  # SECONDS

# This also keeps track of whether or not an incident was triggered successfully
dedup_key = None

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s')


def monitor_tester():
    logging.info('Commencing INTEGRATION TEST...')

    trigg_payload = {
        "event_action": "trigger",
        "routing_key": INT_KEY,
        "payload": {
            "severity": "info",
            "source": HOST,
            "summary": f"[INTEGRATION TEST] process monitor for {PROC_NAME} on {HOST}",
            "custom_details": {
                "info": (
                    f"This is an integration test for the monitoring of {PROC_NAME} on {HOST}. "
                    "It will trigger once when the integration comes online and subsequently "
                    "every first day of the month at 17:00.")
            }
        }
    }

    try:
        response = requests.post(PD_URL, data=json.dumps(trigg_payload))
        dedup_key = response.json()["dedup_key"]
        logging.info(f'{response.status_code} Successfully triggered INTEGRATION TEST with dedup_key: {dedup_key}')

    except requests.exceptions.RequestException as e:
        logging.error(f'Unable to trigger check! {e}')
        return  # No point in continuing if this is the case

    ack_payload = {
        "event_action": "acknowledge",
        "routing_key": INT_KEY,
        "dedup_key": dedup_key
    }

    try:
        response = requests.post(PD_URL, data=json.dumps(ack_payload))
        logging.info(f'{response.status_code} Successfully acknowledged incident with dedup_key: {dedup_key}')

    except requests.exceptions.RequestException as e:
        logging.error(f'Unable to ack check! {e}')


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
        logging.info(f'{response.status_code} Successfully triggered/retriggered with dedup_key {current_dedup}')
        return current_dedup

    except requests.exceptions.RequestException as e:
        logging.error(f'Unable to trigger/retrigger incident! {e}')
        return None


def resolve(dedup_key):
    payload = {
        "event_action": "resolve",
        "routing_key": INT_KEY,
        "dedup_key": dedup_key
    }

    try:
        response = requests.post(PD_URL, data=json.dumps(payload))
        logging.info(f'{response.status_code} Successfully resolved incident with dedup_key: {dedup_key}')
        return True

    except requests.exceptions.RequestException as e:
        logging.error(f'Unable to resolve incident! {e}')
        return False


def check_proc_running(proc_name):
    stdout = subprocess.run(['pgrep', proc_name], stdout=subprocess.PIPE).stdout

    if stdout:
        pids_list = stdout.decode('utf-8').strip().split('\n')
        logging.info(f'Found {proc_name} with PID(s): ' + ', '.join(pids_list))
    else:
        logging.info(f'No PIDs found for {proc_name}')

    return bool(stdout)  # Simple enough. Empty string means its not running.


def monitor():
    logging.info(f'Checking for PID(s) for {PROC_NAME}.')

    running = check_proc_running(PROC_NAME)

    global dedup_key

    # If it's NOT running, go ahead and trigger/retrigger
    if not running:
        logging.info(f'{PROC_NAME} is NOT running. Attempting trigger/retrigger...')

        new_dedup = trigger(dedup_key)

        # If a new dedup is provided, that's the "current dedup"
        dedup_key = new_dedup or dedup_key

    # If it is running and dedup_key is set, that means it needs to be resolved
    elif dedup_key:
        logging.info(f'{PROC_NAME} is running again. Attempting to resolve incident...')

        resolved = resolve(dedup_key)

        # If not able to resolve (connection err), try again next time around
        if resolved:
            dedup_key = None

    else:
        logging.info(f'{PROC_NAME} appears to be running and incident is untriggered.')


def scheduler():
    sched = BlockingScheduler()

    sched.add_job(monitor_tester, 'cron', day='01', hour='17', timezone=TZ)
    sched.add_job(monitor, 'interval', seconds=INTERVAL)

    sched.start()


if __name__ == '__main__':
    try:
        logging.info('Manually running monitor tester for first run "gauge sweep"')
        monitor_tester()
        scheduler()
    except KeyboardInterrupt:
        logging.info("Manually exiting monitor. Goodbye!")
