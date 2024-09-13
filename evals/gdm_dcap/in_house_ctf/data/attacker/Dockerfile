FROM marshw/kali-base

# Update the Kali sources list to ensure it's using a valid repository
RUN echo "deb http://mirror.accum.se/mirror/kali.org/kali/ kali-rolling main non-free contrib" > /etc/apt/sources.list

# Configure environment and install necessary tools
RUN printf "PS1=\"\\u@localhost$ \"" > /root/.bashrc && \
  echo "TERM=xterm" >> /root/.bashrc && \
  # Remove problematic directories
  rm -rf /usr/lib/llvm-1*/build/Debug+Asserts && \
  rm -rf /usr/lib/llvm-1*/build/Release && \
  # Update package list and install required packages
  apt update && \
  apt install -y mongodb gobuster

# Copy necessary files into the image
COPY short_password.lst /usr/share/wordlists/short_password.lst
COPY short_user.lst /usr/share/wordlists/short_user.lst
