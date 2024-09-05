from flask import Flask, jsonify, request
import hvac
import os
import time

app = Flask(__name__)

# Vault configuration
vault_url = os.getenv('VAULT_ADDR', 'http://127.0.0.1:8200')
vault_token = os.getenv('VAULT_TOKEN', 'my_root_token')
ca_cert_path = '/usr/local/share/ca-certificates/kubernetes_ca.crt'
mount_point = 'hostnaming'  # Specify the mount point for KV v2
client = hvac.Client(url=vault_url, token=vault_token, verify=ca_cert_path)

# Locking mechanism using Vault with CAS
class VaultLock:
    def __init__(self, client, mount_point='kv'):
        self.client = client
        self.mount_point = mount_point

    def acquire_lock(self, lock_key, owner, ttl=60, retry_interval=1, max_retries=60):
        path = f'locks/{lock_key}'  # Lock is specific to the prefix
        for attempt in range(max_retries):
            try:
                # Try to create a new key with our owner info
                self.client.secrets.kv.v2.create_or_update_secret(
                    path=path,
                    mount_point=self.mount_point,
                    secret=dict(owner=owner, expires=int(time.time()) + ttl),
                    cas=0  # Only create if it doesn't exist
                )
                app.logger.info(f"Lock {lock_key} acquired by {owner}")
                return True
            except hvac.exceptions.InvalidRequest as e:
                if 'check-and-set parameter did not match' in str(e):
                    # Lock is held by someone else, wait and retry
                    app.logger.warning(f"Lock {lock_key} held by another process. Retrying in {retry_interval} seconds.")
                    time.sleep(retry_interval)
                else:
                    raise
        app.logger.error(f"Failed to acquire lock {lock_key} after {max_retries} attempts")
        return False

    def release_lock(self, lock_key, owner):
        path = f'locks/{lock_key}'
        try:
            # Read current lock data
            result = self.client.secrets.kv.v2.read_secret_version(
                path=path,
                mount_point=self.mount_point,
                raise_on_deleted_version=True  # Explicitly set to avoid warning
            )
            current_data = result['data']['data']

            # Ensure that the lock is owned by the current owner
            if current_data.get('owner') == owner:
                # Option 1: Delete the lock
                self.client.secrets.kv.v2.delete_metadata_and_all_versions(
                    path=path,
                    mount_point=self.mount_point
                )
                app.logger.info(f"Lock {lock_key} released by {owner}")
                return True
            else:
                app.logger.error(f"Cannot release lock {lock_key}. Not owned by {owner}")
                return False
        except hvac.exceptions.InvalidPath:
            app.logger.error(f"Lock {lock_key} does not exist")
            return False

# Function to get or initialize the counter in Vault for a specific prefix
def get_or_initialize_counter(prefix):
    counter_path = f"{prefix}-counter"  # Counter is specific to the prefix
    try:
        counter = client.secrets.kv.v2.read_secret_version(
            path=counter_path,
            mount_point=mount_point,
            raise_on_deleted_version=True  # Explicitly set to avoid warning
        )
        return counter['data']['data']['counter']
    except hvac.exceptions.InvalidPath:
        # Initialize the counter if it doesn't exist
        client.secrets.kv.v2.create_or_update_secret(
            path=counter_path,
            secret={"counter": 0},
            mount_point=mount_point
        )
        return 0

# Function to update the counter in Vault
def update_counter_in_vault(prefix, new_counter):
    counter_path = f"{prefix}-counter"  # Update the specific counter
    client.secrets.kv.v2.create_or_update_secret(
        path=counter_path,
        secret={"counter": new_counter},
        mount_point=mount_point
    )

# Store the generated name in Vault for auditing
def store_generated_name(unique_name):
    name_path = f"names/{unique_name}"
    client.secrets.kv.v2.create_or_update_secret(
        path=name_path,
        secret={"name": unique_name},  # Store each unique name in Vault
        mount_point=mount_point
    )

# Main route for generating unique names
@app.route('/generate-name', methods=['POST'])
def generate_name():
    # Expecting four components in the request: application, role, environment, and prefix
    application = request.json.get('application', 'app')
    role = request.json.get('role', 'role')
    environment = request.json.get('environment', 'env')
    prefix = f"{application}-{role}-{environment}"

    # Initialize the lock with VaultLock class
    owner = f"{application}-{role}-{environment}-{time.time()}"  # Unique owner identifier
    vault_lock = VaultLock(client, mount_point)

    # Acquire the lock for this resource
    if not vault_lock.acquire_lock(prefix, owner):
        return jsonify({"error": "Failed to acquire lock"}), 503

    try:
        # Retrieve and increment the counter for the specific prefix in Vault
        counter = get_or_initialize_counter(prefix)
        new_counter = counter + 1

        # Update the counter in Vault
        update_counter_in_vault(prefix, new_counter)

        # Generate the unique hostname
        unique_name = f"{application}{role}{new_counter}{environment}"
        app.logger.info(f"Generated unique name: {unique_name}")

        # Store the generated name in Vault
        store_generated_name(unique_name)

        return jsonify({"unique_name": unique_name}), 200
    
    except Exception as e:
        app.logger.error(f"Error generating name: {e}")
        return jsonify({"error": "Internal server error"}), 500
    
    finally:
        # Always attempt to release the lock, even if there's an error
        if not vault_lock.release_lock(prefix, owner):
            app.logger.error(f"Failed to release lock {prefix} by {owner}")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
