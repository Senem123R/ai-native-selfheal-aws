#!/bin/bash

# Fix for Windows Git Bash — SAM needs .cmd extension
alias sam='sam.cmd'

# Load .env file
source .env

# Verify key loaded
echo "Key loaded: ${OPENROUTER_KEY:0:10}..."

# Deploy with key injected
sam build && sam deploy --parameter-overrides \
  OpenRouterKey=$OPENROUTER_KEY