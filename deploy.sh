#!/bin/bash

# Fix for Windows Git Bash — SAM needs .cmd extension
alias sam='sam.cmd'

# Fetch current public IP for the demo EC2 instance's SSH access
MY_IP=$(curl -s ifconfig.me)
SSH_ALLOWED_IP="${MY_IP}/32"
echo "Detected IP for SSH access: $SSH_ALLOWED_IP"

# Deploy — only the parameters the CURRENT template.yaml actually declares
sam build && sam deploy --parameter-overrides \
  SshAllowedIp=$SSH_ALLOWED_IP