import os
import boto3
import time

CONNECTIONS_TABLE = os.getenv('CONNECTIONS_TABLE')

ddb = boto3.resource('dynamodb') if CONNECTIONS_TABLE else None

def lambda_handler(event, context):
    try:
        if not CONNECTIONS_TABLE:
            print('No CONNECTIONS_TABLE configured')
            return {'statusCode': 500, 'body': 'Server misconfigured'}

        connection_id = event.get('requestContext', {}).get('connectionId')
        if not connection_id:
            print('No connectionId in event')
            return {'statusCode': 400, 'body': 'Bad request'}

        table = ddb.Table(CONNECTIONS_TABLE)
        table.put_item(Item={
            'connectionId': connection_id,
            'connectedAt': int(time.time())
        })
        return {'statusCode': 200}
    except Exception as e:
        print('Connect handler error', e)
        return {'statusCode': 500, 'body': 'Internal error'}
