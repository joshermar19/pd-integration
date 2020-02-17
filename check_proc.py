from apscheduler.schedulers.blocking import BlockingScheduler
from pytz import timezone
import subprocess
import logging
import requests
import json
import os


TZ = timezone('America/Los_Angeles')
PD_URL = 'https://events.pagerduty.com/v2/enqueue'
INT_KEY = os.environ['INT_KEY']
PROC_NAME = os.environ['PROC_NAME']

# The only configurable "setting". 5 minutes seems fine for now.
INTERVAL = 300  # SECONDS

# This also keeps track of whether or not an incident was triggered successfully
dedup_key = None

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s')


def _get_ec2_metadata(attribute):
    url = f'http://169.254.169.254/latest/meta-data/{attribute}'
    try:
        response = requests.get(url, timeout=2)
        if response.status_code != 200:
            logging.warning(f"{response.status_code} on {url}")
            return None
        return response.text
    except requests.exceptions.RequestException as e:
        logging.warning(f"Could not read EC2 attribute {attribute} {e}")
        return None


def get_trigger_payload(summary, info, severity="critical"):
    instance_id = _get_ec2_metadata("instance-id")
    local_ipv4 = _get_ec2_metadata("local-ipv4")
    local_hostname = _get_ec2_metadata("local-hostname")
    public_ipv4 = _get_ec2_metadata("public-ipv4")
    public_hostname = _get_ec2_metadata("public-hostname")

    return {
        "event_action": "trigger",
        "routing_key": INT_KEY,
        "payload": {
            "severity": severity,
            "source": instance_id,
            "summary": summary.format(PROC_NAME=PROC_NAME, instance_id=instance_id),
            "custom_details": {
                "info": info.format(PROC_NAME=PROC_NAME, instance_id=instance_id, INTERVAL=INTERVAL),
                "process name": PROC_NAME,
                "instance_id": instance_id,
                "local_ipv4": local_ipv4,
                "local_hostname": local_hostname,
                "public_ipv4": public_ipv4,
                "public_hostname": public_hostname
            }
        }
    }


def monitor_check():
    logging.info('Triggering integration check')

    trigg_summary = "[INTEGRATION CHECK] process monitor for {PROC_NAME} on {instance_id}"
    trigg_info = ("This is an integration check for the monitoring of {PROC_NAME} on EC2 instance {instance_id}. "
                  "It will trigger once when the integration comes online and subsequently "
                  "every first day of the month at 17:00.")
    trigg_payload = get_trigger_payload(trigg_summary, trigg_info, severity="info")  # Remember, "critical" severity is the default

    try:
        response = requests.post(PD_URL, data=json.dumps(trigg_payload))
        dedup_key = response.json()["dedup_key"]
        logging.info(f'{response.status_code} Successfully triggered INTEGRATION CHECK with dedup_key: {dedup_key}')

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
    trigg_summary = "{PROC_NAME} has stopped running on {instance_id}"
    trigg_info = ("{PROC_NAME} was not running on EC2 instance {instance_id} within the last {INTERVAL} seconds. "
                  "Please reach out to service owner for troubleshooting.")
    trigg_payload = get_trigger_payload(trigg_summary, trigg_info)

    if dedup_key:  # If this is the first trigger (dedup_key=None), then no dedup is appended to payload
        trigg_payload["dedup_key"] = dedup_key

    try:
        response = requests.post(PD_URL, data=json.dumps(trigg_payload))
        current_dedup = response.json()["dedup_key"]
        logging.info(f'{response.status_code} Successfully triggered/retriggered with dedup_key {current_dedup}')
        return current_dedup

    except requests.exceptions.RequestException as e:
        logging.error(f'Unable to trigger/retrigger incident! {e}')
        return None


def resolve(dedup_key):
    resolve_payload = {
        "event_action": "resolve",
        "routing_key": INT_KEY,
        "dedup_key": dedup_key
    }

    try:
        response = requests.post(PD_URL, data=json.dumps(resolve_payload))
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
    logging.info(f'Checking if {PROC_NAME} is running')

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
        logging.info(f'{PROC_NAME} is running again after a previous trigger. Attempting to resolve incident...')

        resolved = resolve(dedup_key)

        # If not able to resolve (connection err), try again next time around
        if resolved:
            dedup_key = None

    else:
        logging.info(f'{PROC_NAME} appears to be running and incident is untriggered. Doing nothing.')


def scheduler():
    sched = BlockingScheduler()

    sched.add_job(monitor_check, 'cron', day='01', hour='17', timezone=TZ)
    sched.add_job(monitor, 'interval', seconds=INTERVAL)

    sched.start()


if __name__ == '__main__':
    try:
        monitor_check()  # Manually run integration check for first run "gauge sweep"
        scheduler()
    except KeyboardInterrupt:
        logging.info("Manually exiting monitor. Goodbye!")
