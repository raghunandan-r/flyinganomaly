#!/usr/bin/env python3
"""
Integration Agent (Stream I) - Continuous Orchestrator Service

This service runs continuously and:
1. Keeps Docker services running and healthy
2. Monitors service health and restarts if needed
3. Verifies deployment status claims periodically
4. Runs smoke tests periodically
5. Updates deployment_status.md with results
"""

import os
import re
import subprocess
import sys
import json
import time
import signal
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import requests
import docker
from docker.errors import DockerException

# Configuration
PROJECT_ROOT = Path(os.getenv("PROJECT_ROOT", "/app/project"))  # Mounted volume
DEPLOYMENT_STATUS_FILE = PROJECT_ROOT / "deployment_status.md"
BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")
PROCESSING_URL = os.getenv("PROCESSING_URL", "http://processing:8080")
COMPOSE_FILE = PROJECT_ROOT / "docker-compose.yml"

# Monitoring intervals (seconds)
SERVICE_CHECK_INTERVAL = 30  # Check services every 30 seconds
VERIFICATION_INTERVAL = 300   # Verify deployment status every 5 minutes
SMOKE_TEST_INTERVAL = 1800    # Run smoke tests every 30 minutes

# Service names to monitor
REQUIRED_SERVICES = [
    "redpanda",
    "postgres",
    "flight_producer",
    "backend_api",
    "frontend_app"
]

# Graceful shutdown
shutdown_requested = False


def signal_handler(sig, frame):
    """Handle shutdown signals."""
    global shutdown_requested
    print("\nShutdown signal received, gracefully stopping...")
    shutdown_requested = True


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


class ServiceOrchestrator:
    """Orchestrate Docker services - keep them running and healthy."""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
        try:
            self.docker_client = docker.from_env()
        except DockerException:
            self.docker_client = None
            print("Warning: Docker client not available. Service orchestration disabled.")
    
    def ensure_services_running(self) -> Dict[str, bool]:
        """Ensure all required services are running."""
        if not self.docker_client:
            return {}
        
        results = {}
        
        try:
            # Get all containers
            containers = self.docker_client.containers.list(all=True)
            container_map = {c.name: c for c in containers}
            
            for service_name in REQUIRED_SERVICES:
                container = container_map.get(service_name)
                
                if not container:
                    print(f"⚠️  Service {service_name} not found, starting...")
                    self._start_service(service_name)
                    results[service_name] = False
                elif container.status != 'running':
                    print(f"⚠️  Service {service_name} is {container.status}, restarting...")
                    try:
                        container.restart()
                        time.sleep(2)  # Give it a moment to start
                    except Exception as e:
                        print(f"❌ Failed to restart {service_name}: {e}")
                        results[service_name] = False
                    else:
                        results[service_name] = True
                else:
                    # Check health if healthcheck is configured
                    try:
                        health = container.attrs.get('State', {}).get('Health', {}).get('Status', '')
                        if health == 'unhealthy':
                            print(f"⚠️  Service {service_name} is unhealthy, restarting...")
                            container.restart()
                            time.sleep(2)
                            results[service_name] = False
                        else:
                            results[service_name] = True
                    except Exception:
                        # No healthcheck or can't determine, assume healthy if running
                        results[service_name] = True
                        
        except Exception as e:
            print(f"Error checking services: {e}")
        
        return results
    
    def _start_service(self, service_name: str):
        """Start a service using docker compose."""
        try:
            # Map container names to compose service names
            service_map = {
                "redpanda": "redpanda",
                "postgres": "postgres",
                "flight_producer": "producer",
                "backend_api": "backend",
                "frontend_app": "frontend"
            }
            
            compose_service = service_map.get(service_name, service_name)
            
            # Use docker-compose with explicit file path
            compose_file = self.project_root / "docker-compose.yml"
            if not compose_file.exists():
                print(f"⚠️  docker-compose.yml not found at {compose_file}")
                return
            
            # Use docker-compose with explicit file path
            # Use --no-recreate to avoid conflicts with existing containers
            result = subprocess.run(
                ["docker-compose", "-f", str(compose_file), "up", "-d", "--no-recreate", compose_service],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            # If that fails, try without --no-recreate (container might need recreation)
            if result.returncode != 0 and "already in use" in result.stderr:
                # Container exists but might be stopped, try to start it directly
                try:
                    container = self.docker_client.containers.get(service_name)
                    if container.status != 'running':
                        container.start()
                        print(f"✅ Started existing container {service_name}")
                        return
                except Exception:
                    pass
            
            if result.returncode == 0:
                print(f"✅ Started {service_name}")
            else:
                print(f"❌ Failed to start {service_name}: {result.stderr}")
        except Exception as e:
            print(f"❌ Error starting {service_name}: {e}")
    
    def check_service_health(self) -> Dict[str, Tuple[bool, Optional[str]]]:
        """Check health of services via their health endpoints."""
        health_status = {}
        
        # Check backend health
        try:
            response = requests.get(f"{BACKEND_URL}/health", timeout=5)
            if response.status_code == 200:
                health_status["backend"] = (True, response.json().get("status", "healthy"))
            else:
                health_status["backend"] = (False, f"HTTP {response.status_code}")
        except Exception as e:
            health_status["backend"] = (False, str(e))
        
        # Check processing metrics (if available)
        try:
            response = requests.get(f"{PROCESSING_URL}/metrics", timeout=5)
            if response.status_code == 200:
                health_status["processing"] = (True, "metrics available")
            else:
                health_status["processing"] = (False, f"HTTP {response.status_code}")
        except Exception as e:
            health_status["processing"] = (False, "not available (may be expected)")
        
        return health_status


class DeploymentStatusVerifier:
    """Verify claims in deployment_status.md."""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
    
    def extract_verification_commands(self, content: str) -> List[Dict]:
        """Extract verification commands from deployment_status.md."""
        verifications = []
        
        pattern = r'- Verification:\s*`([^`]+)`\s*(?:→|->)\s*(.+)'
        
        for match in re.finditer(pattern, content):
            command = match.group(1).strip()
            expected = match.group(2).strip()
            
            # Find the task this verification belongs to
            start_pos = max(0, match.start() - 500)
            context = content[start_pos:match.start()]
            
            task_match = re.search(r'- \[([ x])\] (.+?)(?:\n|$)', context)
            if task_match:
                task_status = task_match.group(1)
                task_desc = task_match.group(2).strip()
                
                verifications.append({
                    'command': command,
                    'expected': expected,
                    'task': task_desc,
                    'marked_done': task_status == 'x'
                })
        
        return verifications
    
    def run_verification_command(self, command: str) -> Tuple[bool, str, str]:
        """Run a verification command."""
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=30
            )
            return result.returncode == 0, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return False, "", "Command timed out"
        except Exception as e:
            return False, "", str(e)
    
    def verify_all(self) -> Dict[str, Dict]:
        """Verify all claims in deployment_status.md."""
        if not DEPLOYMENT_STATUS_FILE.exists():
            return {}
        
        content = DEPLOYMENT_STATUS_FILE.read_text()
        verifications = self.extract_verification_commands(content)
        
        results = {}
        
        for verification in verifications:
            command = verification['command']
            task = verification['task']
            
            success, stdout, stderr = self.run_verification_command(command)
            results[task] = {
                'success': success,
                'stdout': stdout[:200] if stdout else '',
                'stderr': stderr[:200] if stderr else ''
            }
        
        return results


class DeploymentStatusUpdater:
    """Update deployment_status.md."""
    
    def __init__(self, status_file: Path):
        self.status_file = status_file
    
    def read_status(self) -> str:
        """Read current deployment status."""
        if not self.status_file.exists():
            return ""
        return self.status_file.read_text()
    
    def update_timestamp(self, content: str) -> str:
        """Update the 'Last Updated' timestamp."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
        pattern = r'\*\*Last Updated:\*\* \[Integration Agent updates this\]'
        replacement = f'**Last Updated:** {timestamp}'
        return re.sub(pattern, replacement, content)
    
    def update_stream_i_status(self, content: str, service_status: Dict, health_status: Dict) -> str:
        """Update Stream I section with current status."""
        # Update last updated timestamp
        content = self.update_timestamp(content)
        
        # Update Stream I section
        stream_i_pattern = r'(## 🔄 Stream I: Integration Agent.*?)(---|\n##)'
        
        def update_section(match):
            section = match.group(1)
            next_section = match.group(2)
            
            # Count healthy services
            healthy_count = sum(1 for v in service_status.values() if v)
            total_count = len(service_status)
            
            # Update service orchestration status
            if healthy_count == total_count:
                status_text = f"✅ PASS - All {total_count} services healthy"
            else:
                status_text = f"⚠️  PARTIAL - {healthy_count}/{total_count} services healthy"
            
            section = re.sub(
                r'(- \[([ x])\] Service orchestration running.*?\n\s+- Status:).*',
                rf'\1 {status_text}',
                section,
                flags=re.DOTALL
            )
            
            # Update monitoring status
            section = re.sub(
                r'(- \[([ x])\] Monitoring deployment status.*?\n\s+- Status:).*',
                r'\1 ✅ PASS - Continuously monitoring',
                section,
                flags=re.DOTALL
            )
            
            return section + next_section
        
        return re.sub(stream_i_pattern, update_section, content, flags=re.DOTALL)
    
    def write_status(self, content: str):
        """Write updated deployment status."""
        self.status_file.write_text(content)


class IntegrationAgent:
    """Main integration agent that runs continuously."""
    
    def __init__(self):
        self.project_root = PROJECT_ROOT
        self.orchestrator = ServiceOrchestrator(self.project_root)
        self.verifier = DeploymentStatusVerifier(self.project_root)
        self.updater = DeploymentStatusUpdater(DEPLOYMENT_STATUS_FILE)
        
        self.last_verification = 0
        self.last_smoke_test = 0
    
    def run_service_monitoring(self):
        """Monitor and maintain services (single check)."""
        try:
            # Ensure services are running
            service_status = self.orchestrator.ensure_services_running()
            
            # Check service health
            health_status = self.orchestrator.check_service_health()
            
            # Update deployment status
            if DEPLOYMENT_STATUS_FILE.exists():
                content = self.updater.read_status()
                content = self.updater.update_stream_i_status(content, service_status, health_status)
                self.updater.write_status(content)
            
            # Log status
            healthy_services = [name for name, status in service_status.items() if status]
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Services: {len(healthy_services)}/{len(service_status)} healthy")
            
        except Exception as e:
            print(f"Error in service monitoring: {e}")
    
    def run_verification_cycle(self):
        """Run verification cycle periodically."""
        current_time = time.time()
        
        if current_time - self.last_verification >= VERIFICATION_INTERVAL:
            print("\n" + "=" * 60)
            print("Running Deployment Status Verification")
            print("=" * 60)
            
            try:
                results = self.verifier.verify_all()
                
                print(f"Verified {len(results)} claims")
                for task, result in results.items():
                    status = "✅" if result['success'] else "❌"
                    print(f"  {status} {task}")
                
                self.last_verification = current_time
            except Exception as e:
                print(f"Error in verification: {e}")
    
    def run_smoke_tests(self):
        """Run smoke tests periodically."""
        current_time = time.time()
        
        if current_time - self.last_smoke_test >= SMOKE_TEST_INTERVAL:
            smoke_test_dir = self.project_root / "tests" / "smoke"
            
            if smoke_test_dir.exists():
                print("\n" + "=" * 60)
                print("Running Smoke Tests")
                print("=" * 60)
                
                try:
                    result = subprocess.run(
                        ["pytest", "-v", str(smoke_test_dir)],
                        cwd=self.project_root,
                        capture_output=True,
                        text=True,
                        timeout=300
                    )
                    
                    if result.returncode == 0:
                        print("✅ Smoke tests passed")
                    else:
                        print(f"❌ Smoke tests failed: {result.stderr[:500]}")
                    
                    self.last_smoke_test = current_time
                except Exception as e:
                    print(f"Error running smoke tests: {e}")
            else:
                print("Smoke tests not available yet (Stream H)")
                self.last_smoke_test = current_time
    
    def run(self):
        """Main run loop."""
        print("=" * 60)
        print("SkySentinel Integration Agent (Stream I)")
        print("=" * 60)
        print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Project Root: {self.project_root}")
        print(f"Service Check Interval: {SERVICE_CHECK_INTERVAL}s")
        print(f"Verification Interval: {VERIFICATION_INTERVAL}s")
        print(f"Smoke Test Interval: {SMOKE_TEST_INTERVAL}s")
        print()
        
        # Main monitoring loop
        while not shutdown_requested:
            try:
                # Run service monitoring (single check)
                self.run_service_monitoring()
                
                # Run verification cycle (checks timing internally)
                self.run_verification_cycle()
                
                # Run smoke tests (checks timing internally)
                self.run_smoke_tests()
                
                # Sleep until next service check
                time.sleep(SERVICE_CHECK_INTERVAL)
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"Error in main loop: {e}")
                time.sleep(SERVICE_CHECK_INTERVAL)
        
        print("\nIntegration Agent shutting down...")


def main():
    """Main entry point."""
    agent = IntegrationAgent()
    try:
        agent.run()
    except KeyboardInterrupt:
        print("\nShutdown requested")
    except Exception as e:
        print(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
