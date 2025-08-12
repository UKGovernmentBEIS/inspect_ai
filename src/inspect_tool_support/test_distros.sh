#!/bin/bash

echo "🧪 Cross-architecture inspect-tool-support portability test..."

# Function to detect architecture from container and choose executable
detect_and_choose_executable() {
    local container_id="$1"
    local distro_name="$2"
    
    # Use detect_container_os.sh to get container info
    local detection_output
    detection_output=$(./detect_container_os.sh "$container_id" 2>/dev/null)
    
    if [ $? -ne 0 ]; then
        echo "ERROR: Failed to detect container info"
        return 1
    fi
    
    # Parse the detection output
    local os_line version_line arch_line
    os_line=$(echo "$detection_output" | grep "OS:" | head -n 1)
    version_line=$(echo "$detection_output" | grep "Version:" | head -n 1)
    arch_line=$(echo "$detection_output" | grep "Architecture:" | head -n 1)
    
    # Extract clean values
    local os_info version_info arch_info executable_suffix executable_path
    os_info=$(echo "$os_line" | sed 's/^OS: //')
    version_info=$(echo "$version_line" | sed 's/^Version: //')
    arch_info=$(echo "$arch_line" | sed 's/^Architecture: //')
    
    # Determine executable based on architecture
    if [[ "$arch_line" =~ "x86_64"|"amd64" ]]; then
        executable_suffix="amd64"
    elif [[ "$arch_line" =~ "aarch64"|"arm64" ]]; then
        executable_suffix="arm64"
    else
        echo "ERROR: Unsupported architecture: $arch_info"
        return 1
    fi
    
    executable_path="$(pwd)/container_build/inspect-tool-support-$executable_suffix"
    
    # Write results to temporary file for safe parsing
    local temp_file="/tmp/detect_results_$$"
    cat > "$temp_file" << EOF
DETECTED_OS="$os_info"
DETECTED_VERSION="$version_info"
DETECTED_ARCH="$arch_info"
EXECUTABLE_SUFFIX="$executable_suffix"
EXECUTABLE_PATH="$executable_path"
EOF
    echo "$temp_file"
}

# Check if detect_container_os.sh exists
if [ ! -f "./detect_container_os.sh" ]; then
    echo "❌ detect_container_os.sh not found in current directory"
    exit 1
fi

# Check if executables exist
for arch in amd64 arm64; do
    executable_path="$(pwd)/container_build/inspect-tool-support-$arch"
    if [ ! -f "$executable_path" ]; then
        echo "❌ Executable not found: $executable_path"
        echo "Run ./build_within_container.sh for both architectures first"
        exit 1
    fi
done

# Essential distributions representing different libc implementations
# We'll test both amd64 and arm64 architectures for each distribution
base_distributions=(
    "alpine:latest"           # musl libc
    "ubuntu:18.04"           # older glibc
    "ubuntu:22.04"           # recent glibc  
    "debian:11"              # debian stable
    "debian:10"              # debian oldstable
    "kalilinux/kali-rolling" # kali linux
    "centos:7"               # enterprise linux
    "rockylinux:9"           # modern enterprise
)

# Architectures to test
architectures=("amd64" "arm64")

for distro in "${base_distributions[@]}"; do
    for arch in "${architectures[@]}"; do
        echo ""
        echo "  🔍 Testing $distro [$arch]:"
        
        # Start container with specific platform
        container_id=$(docker run -d --platform "linux/$arch" "$distro" sleep 30 2>/dev/null)
        
        if [ $? -ne 0 ]; then
            echo "    ❌ Failed to start container (platform: linux/$arch)"
            echo "      This may indicate the image doesn't support $arch architecture"
            continue
        fi
        
        # Detect OS, version, and architecture
        echo "    Detecting container details..."
        temp_results_file=$(detect_and_choose_executable "$container_id" "$distro")
        detect_exit_code=$?
        
        if [ $detect_exit_code -ne 0 ]; then
            echo "    ❌ Detection failed: $temp_results_file"
            docker rm -f "$container_id" >/dev/null 2>&1
            continue
        fi
        
        # Source the results from temporary file
        source "$temp_results_file"
        rm -f "$temp_results_file"
        
        # Display detected information
        echo "      📋 OS: $DETECTED_OS"
        if [ -n "$DETECTED_VERSION" ] && [ "$DETECTED_VERSION" != "" ]; then
            echo "      📋 Version: $DETECTED_VERSION"
        fi
        echo "      🏗️  Architecture: $DETECTED_ARCH"
        
        # Verify architecture matches expectation
        expected_arch_pattern=""
        case "$arch" in
            "amd64")
                expected_arch_pattern="x86_64|amd64"
                ;;
            "arm64")
                expected_arch_pattern="aarch64|arm64"
                ;;
        esac
        
        if [[ ! "$DETECTED_ARCH" =~ $expected_arch_pattern ]]; then
            echo "      ⚠️  Warning: Expected $arch but detected $DETECTED_ARCH"
        fi
        
        # Test the executable
        echo -n "    Testing executable (inspect-tool-support-$EXECUTABLE_SUFFIX): "
        if docker run --rm -v "$EXECUTABLE_PATH:/test/app:ro" --platform "linux/$arch" "$distro" /test/app --help >/dev/null 2>&1; then
            echo "✅"
        else
            echo "❌"
        fi
        
        # Cleanup
        docker rm -f "$container_id" >/dev/null 2>&1
    done
done
