#!/usr/bin/env python3
"""
Initialize Kafka topics with correct configurations.

Creates topics as defined in Stream F:
- flights.state: compaction enabled, keyed by icao24
- flights.updates: append-only, 7d retention
- flights.anomalies: append-only, 30d retention
"""

import os
import sys
import logging
import time
from confluent_kafka.admin import AdminClient, NewTopic, ConfigResource
from confluent_kafka import KafkaException

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

REDPANDA_BROKER = os.getenv("REDPANDA_BROKER", "redpanda:9092")

# Topic configurations as per Stream F requirements
TOPICS = {
    "flights.state": {
        "num_partitions": 1,
        "replication_factor": 1,
        "config": {
            "cleanup.policy": "compact",  # Compaction enabled
            "min.insync.replicas": "1",
            "retention.ms": "-1",  # No time-based retention (compaction handles cleanup)
        }
    },
    "flights.updates": {
        "num_partitions": 1,
        "replication_factor": 1,
        "config": {
            "cleanup.policy": "delete",  # Append-only with deletion
            "retention.ms": str(7 * 24 * 60 * 60 * 1000),  # 7 days retention
            "min.insync.replicas": "1",
        }
    },
    "flights.anomalies": {
        "num_partitions": 1,
        "replication_factor": 1,
        "config": {
            "cleanup.policy": "delete",  # Append-only with deletion
            "retention.ms": str(30 * 24 * 60 * 60 * 1000),  # 30 days retention
            "min.insync.replicas": "1",
        }
    }
}


def wait_for_broker(admin_client: AdminClient, max_retries: int = 30, retry_delay: int = 2):
    """Wait for broker to be available."""
    logger.info(f"Waiting for broker at {REDPANDA_BROKER}...")
    
    for i in range(max_retries):
        try:
            # Try to get metadata - this will fail if broker is not available
            metadata = admin_client.list_topics(timeout=5)
            logger.info("Broker is available")
            return True
        except Exception as e:
            if i < max_retries - 1:
                logger.debug(f"Broker not ready (attempt {i+1}/{max_retries}): {e}")
                time.sleep(retry_delay)
            else:
                logger.error(f"Broker not available after {max_retries} attempts: {e}")
                return False
    
    return False


def create_topics(admin_client: AdminClient):
    """Create topics if they don't exist."""
    # Get existing topics
    try:
        metadata = admin_client.list_topics(timeout=10)
        existing_topics = set(metadata.topics.keys())
    except Exception as e:
        logger.error(f"Failed to list topics: {e}")
        return False
    
    # Create topics that don't exist
    topics_to_create = []
    for topic_name, topic_config in TOPICS.items():
        if topic_name in existing_topics:
            logger.info(f"Topic '{topic_name}' already exists, skipping creation")
            # Verify configuration (optional - could update if needed)
            continue
        else:
            logger.info(f"Creating topic '{topic_name}'...")
            new_topic = NewTopic(
                topic_name,
                num_partitions=topic_config["num_partitions"],
                replication_factor=topic_config["replication_factor"],
                config=topic_config["config"]
            )
            topics_to_create.append(new_topic)
    
    if not topics_to_create:
        logger.info("All topics already exist")
        return True
    
    # Create topics
    try:
        futures = admin_client.create_topics(topics_to_create, request_timeout=30)
        
        # Wait for creation to complete
        for topic_name, future in futures.items():
            try:
                future.result()  # Wait for topic creation
                logger.info(f"✅ Successfully created topic '{topic_name}'")
            except Exception as e:
                logger.error(f"❌ Failed to create topic '{topic_name}': {e}")
                return False
        
        logger.info("✅ All topics created successfully")
        return True
        
    except Exception as e:
        logger.error(f"Error creating topics: {e}")
        return False


def verify_topic_configs(admin_client: AdminClient):
    """Verify topic configurations."""
    logger.info("Verifying topic configurations...")
    
    for topic_name, expected_config in TOPICS.items():
        try:
            resource = ConfigResource(ConfigResource.Type.TOPIC, topic_name)
            configs = admin_client.describe_configs([resource], request_timeout=10)
            
            future = configs[resource]
            config = future.result()
            
            # Check key configurations
            cleanup_policy = config.get("cleanup.policy", "").value
            retention_ms = config.get("retention.ms", "").value
            
            expected_cleanup = expected_config["config"]["cleanup.policy"]
            expected_retention = expected_config["config"]["retention.ms"]
            
            if cleanup_policy == expected_cleanup and retention_ms == expected_retention:
                logger.info(f"✅ Topic '{topic_name}' has correct configuration")
            else:
                logger.warning(
                    f"⚠️  Topic '{topic_name}' config mismatch: "
                    f"cleanup.policy={cleanup_policy} (expected {expected_cleanup}), "
                    f"retention.ms={retention_ms} (expected {expected_retention})"
                )
                
        except Exception as e:
            logger.warning(f"Could not verify config for '{topic_name}': {e}")


def main():
    """Main entry point."""
    logger.info("=" * 50)
    logger.info("SkySentinel Topic Initialization")
    logger.info("=" * 50)
    
    # Create admin client
    admin_client = AdminClient({
        "bootstrap.servers": REDPANDA_BROKER,
        "client.id": "skysentinel-topic-init"
    })
    
    # Wait for broker
    if not wait_for_broker(admin_client):
        logger.error("Failed to connect to broker. Exiting.")
        sys.exit(1)
    
    # Create topics
    if not create_topics(admin_client):
        logger.error("Failed to create topics. Exiting.")
        sys.exit(1)
    
    # Verify configurations
    verify_topic_configs(admin_client)
    
    logger.info("=" * 50)
    logger.info("Topic initialization complete")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
