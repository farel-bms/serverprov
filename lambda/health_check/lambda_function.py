import json
import boto3
import psycopg2
import os
import logging
from datetime import datetime
from aws_xray_sdk.core import patch_all

patch_all()

logger = logging.getLogger()
logger.setLevel(logging.INFO)

secrets_client = boto3.client('secretsmanager')
s3_client = boto3.client('s3')
stepfunctions_client = boto3.client('stepfunctions')

_db_credentials = None


def get_db_credentials():
    global _db_credentials
    if _db_credentials:
        return _db_credentials
    secret_arn = os.environ['SECRET_ARN']
    response = secrets_client.get_secret_value(SecretId=secret_arn)
    _db_credentials = json.loads(response['SecretString'])
    return _db_credentials


def check_database():
    try:
        creds = get_db_credentials()
        conn = psycopg2.connect(
            host=creds['host'],
            database=creds['dbname'],
            user=creds['username'],
            password=creds['password'],
            connect_timeout=5
        )
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        conn.close()
        return {'status': 'healthy', 'service': 'rds'}
    except Exception as e:
        return {'status': 'unhealthy', 'service': 'rds', 'error': str(e)}


def check_s3():
    try:
        bucket = os.environ.get('S3_ORDERS_BUCKET', '')
        if not bucket:
            return {'status': 'skipped', 'service': 's3', 'reason': 'no bucket configured'}
        s3_client.head_bucket(Bucket=bucket)
        return {'status': 'healthy', 'service': 's3'}
    except Exception as e:
        return {'status': 'unhealthy', 'service': 's3', 'error': str(e)}


def check_stepfunctions():
    try:
        sf_arn = os.environ.get('STEP_FUNCTIONS_ARN', '')
        if not sf_arn:
            return {'status': 'skipped', 'service': 'stepfunctions', 'reason': 'no ARN configured'}
        stepfunctions_client.describe_state_machine(stateMachineArn=sf_arn)
        return {'status': 'healthy', 'service': 'stepfunctions'}
    except Exception as e:
        return {'status': 'unhealthy', 'service': 'stepfunctions', 'error': str(e)}


def lambda_handler(event, context):
    logger.info(json.dumps({'action': 'health_check_start', 'event': str(event)}))

    checks = {
        'database': check_database(),
        's3': check_s3(),
        'stepfunctions': check_stepfunctions()
    }

    overall_healthy = all(c['status'] in ('healthy', 'skipped') for c in checks.values())
    overall_status = 'healthy' if overall_healthy else 'unhealthy'

    result = {
        'status': overall_status,
        'timestamp': datetime.utcnow().isoformat(),
        'checks': checks,
        'version': os.environ.get('FUNCTION_VERSION', '$LATEST')
    }

    logger.info(json.dumps({'action': 'health_check_complete', 'overall': overall_status}))

    # CodeDeploy lifecycle hook handling
    if 'DeploymentId' in event:
        codedeploy_client = boto3.client('codedeploy')
        lifecycle_event_hook_execution_id = event.get('LifecycleEventHookExecutionId')
        status = 'Succeeded' if overall_healthy else 'Failed'
        try:
            codedeploy_client.put_lifecycle_event_hook_execution_status(
                deploymentId=event['DeploymentId'],
                lifecycleEventHookExecutionId=lifecycle_event_hook_execution_id,
                status=status
            )
        except Exception as e:
            logger.error(f"CodeDeploy hook status update failed: {e}")

    # For API Gateway
    if 'httpMethod' in event:
        status_code = 200 if overall_healthy else 503
        return {
            'statusCode': status_code,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Headers': 'Content-Type,x-api-key,X-Api-Key',
                'Access-Control-Allow-Methods': 'GET,POST,PUT,DELETE,OPTIONS'
            },
            'body': json.dumps(result)
        }

    return result
