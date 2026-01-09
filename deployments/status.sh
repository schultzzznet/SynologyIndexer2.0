#!/usr/bin/env bash
# Show status of all deployments

echo "=========================================="
echo "📊 Multi-Deployment Status"
echo "=========================================="
echo ""

for deployment in deployments/*/; do
    name=$(basename "$deployment")
    
    if [ -f "$deployment/docker-compose.yml" ]; then
        echo "🔹 $name"
        
        cd "$deployment"
        
        # Check if container is running
        if docker compose ps --services --filter "status=running" | grep -q "motion-detector"; then
            echo "   Status: ✅ Running"
            
            # Get port
            PORT=$(docker compose port motion-detector 5050 2>/dev/null | cut -d: -f2)
            if [ -n "$PORT" ]; then
                echo "   Port: $PORT"
            fi
            
            # Get uptime
            UPTIME=$(docker compose ps --format "{{.Status}}" | head -1 | sed 's/Up //')
            echo "   Container: Up $UPTIME"
        else
            echo "   Status: ❌ Stopped"
        fi
        
        cd ../..
        echo ""
    fi
done
