Configuration Guide
===================

This guide explains how to configure storage backends in genro-storage.

Overview
--------

Storage backends are configured through the ``StorageManager.configure()`` method.
You can configure storage from:

1. **Python dictionaries** - for programmatic configuration
2. **YAML files** - for declarative configuration
3. **JSON files** - for declarative configuration

All configuration methods support the same format and backends.

Configuration Methods
---------------------

From Python Dictionaries
~~~~~~~~~~~~~~~~~~~~~~~~~

The most flexible method for programmatic configuration:

.. code-block:: python

    from genro_storage import StorageManager
    
    storage = StorageManager()
    storage.configure([
        {
            'name': 'home',
            'protocol': 'local',
            'path': '/home/user'
        },
        {
            'name': 'uploads',
            'protocol': 's3',
            'bucket': 'my-app-uploads',
            'region': 'eu-west-1'
        }
    ])

From YAML Files
~~~~~~~~~~~~~~~

Best for environment-specific configuration files:

**storage.yaml:**

.. code-block:: yaml

    # Local development storage
    - name: home
      protocol: local
      path: /home/user
    
    - name: temp
      protocol: local
      path: /tmp/app
    
    # Production S3 storage
    - name: uploads
      protocol: s3
      bucket: prod-app-uploads
      region: eu-west-1
      prefix: uploads/
    
    - name: backups
      protocol: s3
      bucket: prod-app-backups
      region: eu-west-1

**Python code:**

.. code-block:: python

    storage = StorageManager()
    storage.configure('/etc/app/storage.yaml')

From JSON Files
~~~~~~~~~~~~~~~

Alternative to YAML:

**storage.json:**

.. code-block:: json

    [
        {
            "name": "home",
            "protocol": "local",
            "path": "/home/user"
        },
        {
            "name": "uploads",
            "protocol": "s3",
            "bucket": "prod-app-uploads",
            "region": "eu-west-1"
        }
    ]

**Python code:**

.. code-block:: python

    storage = StorageManager()
    storage.configure('./config/storage.json')

From a Builder Grammar
~~~~~~~~~~~~~~~~~~~~~~

Configuration can also be written as Python, using the ``StorageConfig``
grammar built on `genro-builders
<https://github.com/genropy/genro-builders>`_. Each mount is an element with a
closed signature, so a misspelled or unsupported attribute is rejected at the
line that writes it rather than at configuration time:

.. code-block:: python

    from genro_storage import StorageConfig, StorageManager

    class AppStorage(StorageConfig):
        def main(self, root):
            m = root.mounts()
            self.local_mounts(m)
            self.cloud_mounts(m)

        def local_mounts(self, m):
            m.local(name='home', base_path='/srv/data')
            m.relative(name='public', path='home:public', permissions='readonly')

        def cloud_mounts(self, m):
            m.s3(name='uploads', base_path='prod-app-uploads')

    storage = StorageManager()
    storage.configure(AppStorage)

``configure()`` accepts the class or an instance. Splitting the recipe into one
method per section is a convention rather than a requirement, and it pays off
in inheritance: a base recipe defines the common mounts and a deployment
subclasses it, overriding a single method without touching ``main``.

Values from the environment
^^^^^^^^^^^^^^^^^^^^^^^^^^^

Fields whose value comes from outside — credentials, endpoints, deploy-time
paths — accept a ``BagResolver`` in place of a literal. The recipe states
*which* variable feeds *which* field, and the value is read when
``configure()`` consumes it:

.. code-block:: python

    from genro_bag.resolvers import EnvResolver

    class AppStorage(StorageConfig):
        def main(self, root):
            m = root.mounts()
            m.s3(name='uploads', base_path='prod-app-uploads',
                 secret_key=EnvResolver('S3_SECRET'))

``EnvResolver`` serializes with the recipe (it carries the variable *name*,
never the value), so a dumped configuration round-trips. For sources other
than the environment, subclass ``BagResolver`` the same way — a resolver
built on a ``lambda`` cannot be serialized and turns the recipe into
something that can no longer be dumped.

Every field that may legitimately come from the environment is
resolver-capable: ``base_path``, ``access_key``, ``secret_key``,
``endpoint_url``, ``token``, ``username``, ``password``, connection hosts, and
the mount-level ``storage_key`` (see :doc:`encryption`). The Azure secret
fields — ``account_key``, ``sas_token``, ``connection_string`` — accept
resolvers as well.

Mounting the grammar in a host document
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The ``@element`` declarations live in a plain mixin, ``StorageGrammar``, which
``StorageConfig`` combines with the builder base. A host dialect — an
application's own configuration document, for instance — can therefore govern
a ``storage`` section with this grammar, referencing it through
``StorageManager.grammar``:

.. code-block:: python

    from genro_builders import BuilderBase, element
    from genro_storage import StorageManager

    class SiteConfig(BuilderBase):
        @element(_meta={'subbuilder': 'app:grammar'})
        def storage(self, app=None):
            """Envelope node whose subtree is governed by ``app.grammar``."""

    class MySite(SiteConfig):
        def main(self, root):
            m = root.storage(app=StorageManager).mounts()
            m.local(name='home', base_path='/srv/data')

The attribute is inherited through the MRO, so a ``StorageManager`` subclass
carries — or specializes — its own grammar for free.

Storage Backend Types
---------------------

Local Filesystem
~~~~~~~~~~~~~~~~

Access files on the local filesystem.

**Required fields:**

- ``name``: Mount point name
- ``type``: Must be ``"local"``
- ``path``: Absolute path to base directory

**Optional fields:**

- ``default_encrypted``: default of the per-write ``encrypted`` parameter on
  this mount — ``True`` for the default domain, a domain name, or ``False``
  (the default). A ``relative`` mount takes the same option, as its own: the
  parent's default does not leak through. See :doc:`encryption`.

**Example:**

.. code-block:: yaml

    - name: home
      protocol: local
      path: /home/user
    
    - name: temp
      protocol: local
      path: /tmp/app

.. code-block:: python

    storage.configure([
        {'name': 'home', 'protocol': 'local', 'path': '/home/user'},
        {'name': 'temp', 'protocol': 'local', 'path': '/tmp/app'}
    ])

**Usage:**

.. code-block:: python

    node = storage.node('home:documents/report.pdf')
    content = node.read()

Amazon S3
~~~~~~~~~

Access files in Amazon S3 buckets.

**Required fields:**

- ``name``: Mount point name
- ``type``: Must be ``"s3"``
- ``bucket``: S3 bucket name

**Optional fields:**

- ``prefix``: Path prefix within bucket (default: ``""``)
- ``region``: AWS region (default: from AWS config)
- ``anon``: Anonymous access (default: ``False``)
- ``key``: AWS access key (default: from AWS config)
- ``secret``: AWS secret key (default: from AWS config)
- ``endpoint_url``: Custom S3 endpoint for S3-compatible services
- ``version_aware``: List object versions (default: ``True``). Set ``False``
  for S3-compatible servers without ``ListObjectVersions``, such as Garage;
  delete, list, copy and move then work, and versioning capabilities are off

**Example:**

.. code-block:: yaml

    # Standard S3
    - name: uploads
      protocol: s3
      bucket: my-app-uploads
      region: eu-west-1
      prefix: uploads/
    
    # With credentials
    - name: backups
      protocol: s3
      bucket: my-app-backups
      region: us-east-1
      key: AKIAIOSFODNN7EXAMPLE
      secret: wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
    
    # Anonymous public bucket
    - name: public-data
      protocol: s3
      bucket: public-datasets
      anon: true

**Usage:**

.. code-block:: python

    # Upload file
    node = storage.node('uploads:2024/report.pdf')
    node.write(pdf_data, mode='wb')
    
    # List directory
    folder = storage.node('uploads:2024')
    for file in folder.children():
        print(f"{file.basename}: {file.size} bytes")

Google Cloud Storage
~~~~~~~~~~~~~~~~~~~~

Access files in Google Cloud Storage buckets.

**Required fields:**

- ``name``: Mount point name
- ``type``: Must be ``"gcs"``
- ``bucket``: GCS bucket name

**Optional fields:**

- ``prefix``: Path prefix within bucket (default: ``""``)
- ``token``: Path to service account JSON key file
- ``project``: GCP project ID

**Example:**

.. code-block:: yaml

    - name: backups
      protocol: gcs
      bucket: my-app-backups
      project: my-gcp-project
      token: /etc/secrets/gcp-service-account.json

.. code-block:: python

    storage.configure([{
        'name': 'backups',
        'protocol': 'gcs',
        'bucket': 'my-app-backups',
        'token': '/etc/secrets/gcp-service-account.json'
    }])

Azure Blob Storage
~~~~~~~~~~~~~~~~~~

Access files in Azure Blob Storage containers.

**Required fields:**

- ``name``: Mount point name
- ``type``: Must be ``"azure"``
- ``container``: Container name
- ``account_name``: Storage account name

**Optional fields:**

- ``account_key``: Storage account key
- ``sas_token``: Shared access signature token
- ``connection_string``: Full connection string

**Example:**

.. code-block:: yaml

    - name: archive
      protocol: azure
      container: archives
      account_name: mystorageaccount
      account_key: xxxxxxxxxxxxxxxxxxxxx

HTTP Storage (Read-Only)
~~~~~~~~~~~~~~~~~~~~~~~~~

Access files via HTTP/HTTPS (read-only).

**Required fields:**

- ``name``: Mount point name
- ``type``: Must be ``"http"``
- ``base_url``: Base URL for HTTP requests

**Example:**

.. code-block:: yaml

    - name: cdn
      protocol: http
      base_url: https://cdn.example.com

.. code-block:: python

    storage.configure([{
        'name': 'cdn',
        'protocol': 'http',
        'base_url': 'https://cdn.example.com'
    }])
    
    # Read-only access
    node = storage.node('cdn:assets/logo.png')
    image_data = node.read(mode='rb')

Memory Storage (Testing)
~~~~~~~~~~~~~~~~~~~~~~~~~

In-memory storage for testing and development.

**Required fields:**

- ``name``: Mount point name
- ``type``: Must be ``"memory"``

**Example:**

.. code-block:: python

    # Perfect for unit tests
    storage.configure([{'name': 'test', 'protocol': 'memory'}])

    node = storage.node('test:temp.txt')
    node.write("test data")
    assert node.read() == "test data"

Permission Control
------------------

Configure access permissions for any storage backend to restrict operations.

Permission Levels
~~~~~~~~~~~~~~~~~

Three permission levels are available:

- ``readonly``: Only read operations (read, exists, list)
- ``readwrite``: Read and write operations, but no delete
- ``delete``: Full access including delete (default)

**Example:**

.. code-block:: python

    storage.configure([
        # Read-only access to public data
        {'name': 'public', 'protocol': 'http', 'base_url': 'https://cdn.example.com',
         'permissions': 'readonly'},

        # Read-write but no delete for backups
        {'name': 'backups', 'protocol': 'gcs', 'bucket': 'my-backups',
         'permissions': 'readwrite'},

        # Full access (default)
        {'name': 'uploads', 'protocol': 's3', 'bucket': 'my-uploads'}
    ])

Using Permissions
~~~~~~~~~~~~~~~~~

Permissions are validated at configuration time and enforced at runtime:

.. code-block:: python

    # Read-only mount
    storage.configure([
        {'name': 'public', 'protocol': 's3', 'bucket': 'public-data',
         'permissions': 'readonly'}
    ])

    node = storage.node('public:file.txt')

    # Allowed operations
    content = node.read()
    exists = node.exists
    files = node.children()

    # Raises StoragePermissionError
    node.write("data")
    node.delete()
    node.mkdir()

YAML Configuration
~~~~~~~~~~~~~~~~~~

.. code-block:: yaml

    # Read-only CDN
    - name: cdn
      protocol: http
      base_url: https://cdn.example.com
      permissions: readonly

    # Read-write backups (no delete)
    - name: backups
      protocol: gcs
      bucket: my-backups
      permissions: readwrite

    # Full access uploads
    - name: uploads
      protocol: s3
      bucket: my-uploads
      permissions: delete

Permission Validation
~~~~~~~~~~~~~~~~~~~~~

Permissions are validated against backend capabilities:

.. code-block:: python

    # Invalid: HTTP is read-only, cannot request readwrite
    storage.configure([
        {'name': 'cdn', 'protocol': 'http', 'base_url': 'https://cdn.example.com',
         'permissions': 'readwrite'}  # Error!
    ])
    # Raises: StorageConfigError: Backend is read-only

Best Practices
~~~~~~~~~~~~~~

1. **Principle of least privilege** - Use ``readonly`` when possible
2. **Protect backups** - Use ``readwrite`` to prevent accidental deletion
3. **Validate at startup** - Permissions are checked at configuration time
4. **Use for security** - Restrict access to sensitive storage locations

Advanced Configuration
----------------------

Multiple Configurations
~~~~~~~~~~~~~~~~~~~~~~~

You can call ``configure()`` multiple times. Mounts with the same name
are replaced:

.. code-block:: python

    # Initial setup
    storage.configure([
        {'name': 'home', 'protocol': 'local', 'path': '/home/user'}
    ])
    
    # Add more mounts later
    storage.configure([
        {'name': 'uploads', 'protocol': 's3', 'bucket': 'my-bucket'}
    ])
    
    # Replace existing mount
    storage.configure([
        {'name': 'home', 'protocol': 'local', 'path': '/mnt/newlocation'}
    ])

Environment-Specific Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Use different configuration files per environment:

.. code-block:: python

    import os
    
    storage = StorageManager()
    
    # Load environment-specific config
    env = os.getenv('APP_ENV', 'development')
    config_file = f'/etc/app/storage-{env}.yaml'
    storage.configure(config_file)

**storage-development.yaml:**

.. code-block:: yaml

    - name: uploads
      protocol: local
      path: /tmp/dev-uploads

**storage-production.yaml:**

.. code-block:: yaml

    - name: uploads
      protocol: s3
      bucket: prod-uploads
      region: eu-west-1

Configuration from Environment Variables
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Build configuration dynamically from environment:

.. code-block:: python

    import os
    
    storage = StorageManager()
    storage.configure([
        {
            'name': 'uploads',
            'protocol': 's3',
            'bucket': os.getenv('S3_BUCKET'),
            'region': os.getenv('AWS_REGION', 'eu-west-1'),
            'key': os.getenv('AWS_ACCESS_KEY_ID'),
            'secret': os.getenv('AWS_SECRET_ACCESS_KEY')
        }
    ])

Checking Configured Mounts
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # List all configured mounts
    print(storage.get_mount_names())
    # ['home', 'uploads', 'temp']
    
    # Check if mount exists
    if storage.has_mount('uploads'):
        node = storage.node('uploads:file.txt')
    else:
        print("Uploads storage not configured")

Complete Example
----------------

**config/storage-prod.yaml:**

.. code-block:: yaml

    # Local temporary storage
    - name: temp
      protocol: local
      path: /tmp/app
    
    # User uploads to S3
    - name: uploads
      protocol: s3
      bucket: prod-app-uploads
      region: eu-west-1
      prefix: uploads/
    
    # Backups to GCS
    - name: backups
      protocol: gcs
      bucket: prod-app-backups
      token: /etc/secrets/gcp-key.json
    
    # Static assets from CDN
    - name: cdn
      protocol: http
      base_url: https://cdn.example.com

**Python application:**

.. code-block:: python

    from genro_storage import StorageManager
    
    # Initialize and configure
    storage = StorageManager()
    storage.configure('/etc/app/storage-prod.yaml')
    
    # Process upload
    upload = storage.node('temp:processing/image.jpg')
    upload.write(uploaded_data, mode='wb')
    
    # Save to S3
    final = storage.node('uploads:2024/images/photo.jpg')
    upload.copy_to(final)
    
    # Backup to GCS
    backup = storage.node('backups:daily/2024-10-26/photo.jpg')
    final.copy_to(backup)
    
    # Cleanup temp
    upload.delete()
    
    # Access CDN asset
    logo = storage.node('cdn:assets/logo.png')
    logo_data = logo.read(mode='rb')

Best Practices
--------------

1. **Use YAML for declarative configs** - easier to read and maintain
2. **Separate configs per environment** - development, staging, production
3. **Store credentials securely** - use secrets managers, not config files
4. **Use meaningful mount names** - ``uploads``, ``backups``, not ``s3_1``
5. **Configure once at startup** - don't reconfigure during runtime
6. **Use prefixes in cloud storage** - organize files within buckets
7. **Test with memory backend** - fast, no cleanup needed

Troubleshooting
---------------

**Mount not found error:**

.. code-block:: python

    # Error: StorageNotFoundError: Mount point 'uploads' not found
    node = storage.node('uploads:file.txt')
    
    # Check configured mounts
    print(storage.get_mount_names())
    
    # Verify mount is configured
    if not storage.has_mount('uploads'):
        storage.configure([{'name': 'uploads', 'protocol': 's3', 'bucket': 'my-bucket'}])

**Invalid configuration:**

.. code-block:: python

    # Missing required field
    storage.configure([{'name': 'uploads', 'protocol': 's3'}])  # Missing 'bucket'!
    # Raises: StorageConfigError: Missing required field 'bucket' for S3 storage

**Path escaping base directory:**

.. code-block:: python

    storage.configure([{'name': 'home', 'protocol': 'local', 'path': '/home/user'}])
    node = storage.node('home:../../../etc/passwd')
    # Raises: ValueError: Path escapes base directory
