#!/bin/bash

# Update and install prerequisites
apt-get update -qq
apt-get -y install -qq wget apt-transport-https gnupg software-properties-common

# Install tshark
apt-get -y install -qq tshark

# Add Microsoft's package signing key and repository
wget https://packages.microsoft.com/config/ubuntu/$(lsb_release -sr)/packages-microsoft-prod.deb -O packages-microsoft-prod.deb
dpkg -i packages-microsoft-prod.deb
apt-get update

# Install .NET SDK
apt-get -y install -qq dotnet-sdk-6.0

# Install ilspycmd as a global tool using .NET
dotnet tool install ilspycmd -g

# Install mono-complete
apt-get -y install -qq mono-complete

# Clean up downloaded package
rm packages-microsoft-prod.deb
