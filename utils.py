import logging
import os
import sys
from typing import Any, Dict, Union

import boto3
import chainlit.data as cl_data
from chainlit.data.base import BaseStorageClient
from chainlit.data.sql_alchemy import SQLAlchemyDataLayer
from chainlit.logger import logger

# If Python’s builtin readline module is previously loaded, elaborate line editing and history features will be available.
# https://rich.readthedocs.io/en/stable/console.html#input
from rich.console import Console
from rich.logging import RichHandler
from rich.traceback import install
from sqlalchemy import create_engine, text


class MinioStorageClient(BaseStorageClient):
    """
    Copied from https://github.com/rongfengliang/chainlit-pg-learning/blob/9e9da095cc0bd447dfcb59504a835b69cef9cf3f/minio.py#L6.

    Original author:
    - https://github.com/rongfengliang
    - 1141591465@qq.com
    - cnblogs.com/rongfengliang

    Class to enable MinIO storage provider

    params:
        bucket: Bucket name, should be set with public access
        endpoint_url: MinIO server endpoint, defaults to "http://localhost:9000"
        aws_access_key_id: Default is "minioadmin"
        aws_secret_access_key: Default is "minioadmin"
        verify_ssl: Set to True only if not using HTTP or HTTPS with self-signed SSL certificates
    """

    def __init__(
        self,
        bucket: str,
        endpoint_url: str = "http://localhost:9000",
        aws_access_key_id: str = "minioadmin",
        aws_secret_access_key: str = "minioadmin",
        verify_ssl: bool = False,
    ):
        try:
            self.bucket = bucket
            self.endpoint_url = endpoint_url
            self.client = boto3.client(
                "s3",
                endpoint_url=self.endpoint_url,
                aws_access_key_id=aws_access_key_id,
                aws_secret_access_key=aws_secret_access_key,
                verify=verify_ssl,
            )
            logger.info("MinioStorageClient initialized")
        except Exception as e:
            logger.warn(f"MinioStorageClient initialization error: {e}")

    async def upload_file(
        self,
        object_key: str,
        data: Union[bytes, str],
        mime: str = "application/octet-stream",
        overwrite: bool = True,
    ) -> Dict[str, Any]:
        try:
            self.client.put_object(
                Bucket=self.bucket, Key=object_key, Body=data, ContentType=mime
            )
            url = f"{self.endpoint_url}/{self.bucket}/{object_key}"
            return {"object_key": object_key, "url": url}
        except Exception as e:
            logger.warn(f"MinioStorageClient, upload_file error: {e}")
            return {}


def set_up_data_layer(sqlite_file_path: str = ".chainlit/data.db"):
    # Import sqlalchemy. Connect to `sqlite+aiosqlite:///:memory:`.
    # Read the SQL file at `.chainlit/schema.sql`. Execute the SQL commands in the file to create the tables.
    engine = create_engine(f"sqlite:///{sqlite_file_path}")
    with open(".chainlit/schema.sql") as f:
        schema_sql = f.read()
    sql_statements = schema_sql.strip().split(";")  # Split by semicolon
    with engine.connect() as conn:
        for statement in sql_statements:
            if statement.strip():  # Avoid executing empty statements
                conn.execute(text(statement))

    #
    storage_client = MinioStorageClient(
        bucket="chainlit",
        endpoint_url="http://localhost:9000",
        aws_access_key_id=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
        aws_secret_access_key=os.getenv("MINIO_SECRET_KEY", "minioadmin"),
        verify_ssl=False,
    )
    # Set the data layer to use the SQLAlchemyDataLayer with the connection info.
    cl_data._data_layer = SQLAlchemyDataLayer(
        conninfo=f"sqlite+aiosqlite:///{sqlite_file_path}",  # https://stackoverflow.com/a/72334692/27163563,
        storage_provider=storage_client,
    )


def set_up_logging(should_use_rich: bool = True):
    console = Console()
    # https://rich.readthedocs.io/en/latest/logging.html#handle-exceptions
    logging.basicConfig(
        # This can get really verbose if set to `logging.DEBUG`.
        level=logging.INFO,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[
            (
                RichHandler(rich_tracebacks=True, console=console)
                if should_use_rich
                else logging.StreamHandler()
            )
        ],
        # This function does nothing if the root logger already has handlers configured,
        # unless the keyword argument force is set to True.
        # https://docs.python.org/3/library/logging.html#logging.basicConfig
        force=True,
    )
    logger = logging.getLogger(__name__)

    if should_use_rich:
        # https://rich.readthedocs.io/en/stable/traceback.html#traceback-handler
        logger.debug("Installing rich traceback handler.")
        old_traceback_handler = install(show_locals=True, console=console)
        logger.debug(
            f"The global traceback handler has been swapped from {old_traceback_handler} to {sys.excepthook}."
        )
