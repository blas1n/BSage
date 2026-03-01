"""S3 output Plugin — syncs vault files to AWS S3."""

from bsage.plugin import plugin


@plugin(
    name="s3-output",
    version="1.0.0",
    category="output",
    description="Sync vault files to an AWS S3 bucket",
    trigger={"type": "write_event"},
    credentials=[
        {"name": "aws_access_key_id", "description": "AWS access key ID", "required": True},
        {"name": "aws_secret_access_key", "description": "AWS secret access key", "required": True},
        {"name": "bucket", "description": "S3 bucket name", "required": True},
        {"name": "prefix", "description": "S3 key prefix (default: bsage/)", "required": False},
        {"name": "region", "description": "AWS region (default: us-east-1)", "required": False},
    ],
)
async def execute(context) -> dict:
    """Upload the written vault file to S3."""
    import asyncio
    from pathlib import Path

    import boto3

    creds = context.credentials
    bucket = creds.get("bucket", "")
    prefix = creds.get("prefix", "bsage/")
    region = creds.get("region", "us-east-1")

    event_data = context.input_data or {}
    source_path = Path(event_data.get("path", ""))

    if not source_path.exists():
        return {"synced": False, "error": "source file does not exist"}

    # Build S3 key preserving vault structure
    vault_path = Path(context.config.get("vault_path", "./vault")).resolve()
    try:
        relative = source_path.resolve().relative_to(vault_path)
    except ValueError:
        relative = Path(source_path.name)

    s3_key = f"{prefix}{relative}"
    content = await asyncio.to_thread(source_path.read_text, "utf-8")

    def _upload() -> None:
        client = boto3.client(
            "s3",
            aws_access_key_id=creds.get("aws_access_key_id", ""),
            aws_secret_access_key=creds.get("aws_secret_access_key", ""),
            region_name=region,
        )
        client.put_object(
            Bucket=bucket,
            Key=s3_key,
            Body=content.encode("utf-8"),
            ContentType="text/markdown",
        )

    await asyncio.to_thread(_upload)
    return {"synced": True, "bucket": bucket, "key": s3_key}


@execute.setup
def setup(cred_store):
    """Configure AWS S3 credentials with bucket access check."""
    import asyncio

    import click

    click.echo("S3 Output Setup")
    access_key = click.prompt("  AWS access key ID")
    secret_key = click.prompt("  AWS secret access key", hide_input=True)
    bucket = click.prompt("  S3 bucket name")
    prefix = click.prompt("  Key prefix", default="bsage/")
    region = click.prompt("  AWS region", default="us-east-1")

    import boto3

    try:
        client = boto3.client(
            "s3",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )
        client.head_bucket(Bucket=bucket)
        click.echo(f"  Verified bucket: {bucket}")
    except Exception as exc:
        click.echo(f"Error: S3 access failed — {exc}", err=True)
        raise SystemExit(1) from None

    data = {
        "aws_access_key_id": access_key,
        "aws_secret_access_key": secret_key,
        "bucket": bucket,
        "prefix": prefix,
        "region": region,
    }
    asyncio.run(cred_store.store("s3-output", data))
