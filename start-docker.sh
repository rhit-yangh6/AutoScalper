#!/bin/bash
# AutoScalper Docker Startup Script
# This script starts IB Gateway in Docker with auto-login

set -e

echo "================================================"
echo "  AutoScalper - IB Gateway Docker Startup"
echo "================================================"
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Error: Docker is not running"
    echo "   Please start Docker Desktop and try again"
    exit 1
fi

# Check if .env exists
if [ ! -f .env ]; then
    echo "❌ Error: .env file not found"
    echo "   Please copy .env.example to .env and configure it:"
    echo "   cp .env.example .env"
    echo "   nano .env"
    exit 1
fi

# Check if IB credentials are configured
if grep -q "your_ib_username" .env; then
    echo "⚠️  Warning: .env still contains placeholder values"
    echo "   Please edit .env and add your IB credentials:"
    echo "   - IB_USERNAME"
    echo "   - IB_PASSWORD"
    echo ""
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Create settings directory if it doesn't exist
mkdir -p docker/ibgateway/settings
echo "✓ Created docker/ibgateway/settings directory"

# Start IB Gateway container
echo ""
echo "Starting IB Gateway container..."
docker-compose up -d ibgateway

# Wait for container to start
echo ""
echo "Waiting for Gateway to initialize (60 seconds)..."
sleep 5

# Show logs
echo ""
echo "================================================"
echo "  Gateway Startup Logs"
echo "================================================"
docker-compose logs --tail=30 ibgateway

echo ""
echo "================================================"
echo "  Status"
echo "================================================"

# Check if container is running
if docker-compose ps ibgateway | grep -q "Up"; then
    echo "✅ IB Gateway container is running"
    echo ""
    echo "Next steps:"
    echo "1. Wait 60-90 seconds for Gateway to fully initialize"
    echo "2. Check connection: nc -zv localhost 4002"
    echo "3. Start your bot: python -m src.orchestrator.main"
    echo ""
    echo "View logs: docker-compose logs -f ibgateway"
    echo "Stop: docker-compose stop ibgateway"
else
    echo "❌ IB Gateway container failed to start"
    echo ""
    echo "Troubleshooting:"
    echo "1. Check credentials in .env"
    echo "2. View full logs: docker-compose logs ibgateway"
    echo "3. Check Docker resources: docker stats"
    exit 1
fi

echo ""
echo "To view live logs, run:"
echo "  docker-compose logs -f ibgateway"
echo ""
