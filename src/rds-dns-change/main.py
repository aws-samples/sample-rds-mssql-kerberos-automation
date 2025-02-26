import json
import boto3
import os
import pymssql
from botocore.exceptions import WaiterError

def lambda_handler(event, context):
    # Retrieve environment variables
    ec2_instance_id = os.environ['EC2_INSTANCE_ID']
    rds_endpoint = os.environ['RDS_ENDPOINT']
    rds_port = os.environ['RDS_PORT']
    secret_arn = os.environ['SECRET_ARN']
    ssm_document = os.environ['SSM_DOCUMENT']
    ad_domain = os.environ['AD_DOMAIN']

    # Initialize AWS clients
    ssm_client = boto3.client('ssm')
    secrets_client = boto3.client('secretsmanager')

    # Log the received event
    print("Received event:", json.dumps(event))

    # Retrieve parameters from Secrets Manager
    try:
        secret_value = secrets_client.get_secret_value(SecretId=secret_arn)
        secret_string = secret_value['SecretString']
        parameters = json.loads(secret_string)
        ad_username = parameters['CUSTOMER_MANAGED_ACTIVE_DIRECTORY_USERNAME']
        ad_password = parameters['CUSTOMER_MANAGED_ACTIVE_DIRECTORY_PASSWORD']
    except Exception as e:
        raise e

    # SQL Server connection
    conn = None
    cursor = None
    try:
        full_username = f"{ad_domain}\\{ad_username}"

        # Connect to the SQL Server instance
        conn = pymssql.connect(server=rds_endpoint, port=rds_port, user=full_username, password=ad_password,
                               database='master')

        # Execute SQL command
        cursor = conn.cursor()
        cursor.execute("SELECT @@SERVERNAME")
        server_name = cursor.fetchone()
        if server_name:
            print(f"Server Name: {server_name[0]}")
        else:
            print("No server name returned from the query.")

    except Exception as e:
        print("Error connecting to or querying SQL Server:", e)
        raise e
    finally:
        # Ensure resources are closed properly
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    # Execute the SSM document on the EC2 instance
    try:
        server_name_param = server_name[0] if server_name else "Unknown"
        response = ssm_client.send_command(
            InstanceIds=[ec2_instance_id],
            DocumentName=ssm_document,
            Parameters={
                'RDSEndpoint': [rds_endpoint],
                'RDSPort': [rds_port],
                'ServerNames': [server_name_param]
            },
            TimeoutSeconds=600
        )
        command_id = response['Command']['CommandId']
        print(f"Command sent to EC2 instance. Command ID: {command_id}")

        # Wait for the command to be executed using a waiter
        waiter = ssm_client.get_waiter('command_executed')
        try:
            waiter.wait(
                CommandId=command_id,
                InstanceId=ec2_instance_id,
            )
            print("Command execution completed successfully.")
        except WaiterError as ex:
            print(f"Error waiting for command execution:", ex)
            raise ex

        # Get the command output after successful execution
        invocation_response = ssm_client.get_command_invocation(
            CommandId=command_id,
            InstanceId=ec2_instance_id,
        )
        print("Command output:", invocation_response['StandardOutputContent'])

    except Exception as e:
        print("Error executing SSM command:", e)
        raise e

    return {
        'statusCode': 200,
        'body': json.dumps('Process completed successfully.')
    }
