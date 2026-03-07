#!/bin/bash
# Run this from your Mac to deploy to the live server
# Usage: bash deploy-live.sh

echo ">>> Deploying to live server..."
ssh fortezo@137.184.32.193 "sudo bash /odoo14/deploy.sh"
echo ">>> Done. Go to browser -> Apps -> custom_purchase_flow -> Upgrade."
