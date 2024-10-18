package main

import (
	"bufio"
	"fmt"
	"io"
	"net"
	"strings"
	"sync"
	"time"
)

func main() {
	cache := &Cache{
		data:  make(map[string]string),
		mutex: sync.RWMutex{},
	}

	go func(cache *Cache) {
		for {
			time.Sleep(60 * time.Second)
			cache.Clear()
			fmt.Println("Cache cleared!")
		}
	}(cache)

	listener, err := net.Listen("tcp", "0.0.0.0:8080")
	if err != nil {
		fmt.Println("Error starting server:", err.Error())
		return
	}
	defer listener.Close()

	fmt.Println("Server listening on 0.0.0.0:8080")

	for {
		conn, err := listener.Accept()
		if err != nil {
			fmt.Println("Error accepting connection:", err.Error())
			continue
		}

		go handleConnection(conn, cache)
	}
}

func handleConnection(conn net.Conn, cache *Cache) {
	reader := bufio.NewReader(conn)
	writer := bufio.NewWriter(conn)

	defer conn.Close()

	serverConn, err := net.Dial("tcp", "nginx:80")
	if err != nil {
		fmt.Println("Error connecting to nginx:", err.Error())
	}
	defer serverConn.Close()

	for {

		requestLine, err := reader.ReadString('\n')
		if err != nil {
			fmt.Println("Error reading request:", err.Error())
			return
		}

		parts := strings.Split(requestLine, " ")
		if len(parts) != 3 {
			fmt.Println("Invalid request line:", requestLine)
			return
		}

		method := parts[0]
		path := parts[1]
		version := parts[2]

		fmt.Printf("Received request: %s %s %s\n", method, path, version)

		headers := make(map[string]string)

		for {
			line, err := reader.ReadString('\n')
			if err != nil || line == "\r\n" {
				break
			}

			parts := strings.SplitN(line, ":", 2)
			if len(parts) != 2 {
				continue
			}

			key := strings.TrimSpace(parts[0])
			value := strings.TrimSpace(parts[1])
			headers[key] = value
		}

		host := headers["Host"]

		cacheKey := method + " " + path
		if cachedResponse, ok := cache.Get(cacheKey); ok {
			fmt.Println("Cache hit for", cacheKey)

			writer.WriteString(cachedResponse)
			writer.Flush()
			return
		}

		// These are unsupported. Let's ignore them.
		headersToRemove := [5]string{"Transfer-Encoding", "Expect", "Forwarded"}
		for _, h := range headersToRemove {
			delete(headers, h)
		}

		response, headers, err := forwardRequest(serverConn, method, path, version, headers, host, reader)
		if err != nil {
			fmt.Println("Error forwarding request:", err.Error())
			return
		}

		should_cache := true
		for k, v := range headers {
			if path == "/admin/flag" || (k == "Cache-Control" && v == "no-store") {
				should_cache = false
			}
		}
		if should_cache {
			cache.Set(cacheKey, response)
		}

		writer.WriteString(response)
		writer.Flush()
	}
}

func forwardRequest(serverConn net.Conn, method, path, version string, headers map[string]string, host string, reader *bufio.Reader) (string, map[string]string, error) {

	serverWriter := bufio.NewWriter(serverConn)
	serverReader := bufio.NewReader(serverConn)

	requestLine := fmt.Sprintf("%s %s %s", method, path, version)

	requestHeaders := ""
	for key, value := range headers {
		if key == "Host" {
			value = "blog:8002"
		}
		requestHeaders += fmt.Sprintf("%s: %s\r\n", key, value)
	}

	request := requestLine + requestHeaders + "\r\n"

	_, err := serverWriter.WriteString(request)
	if err != nil {
		return "", nil, err
	}

	contentLength := headers["Content-Length"]

	if contentLength != "" {
		length := 0
		if _, err := fmt.Sscanf(contentLength, "%d", &length); err != nil {
			return "", nil, fmt.Errorf("invalid Content-Length header: %s", contentLength)
		}

		fmt.Printf("Body length: %d\n", length)

		body := make([]byte, length)
		_, err := io.ReadFull(reader, body)
		if err != nil {
			return "", nil, fmt.Errorf("error reading request body: %s", err.Error())
		}

		_, err = serverWriter.Write(body)
		if err != nil {
			return "", nil, fmt.Errorf("error sending request body: %s", err.Error())
		}
	}

	err = serverWriter.Flush()
	if err != nil {
		return "", nil, fmt.Errorf("error flushing request body writer: %s", err.Error())
	}

	responseStatus, err := serverReader.ReadString('\n')
	if err != nil {
		return "", nil, fmt.Errorf("error reading server response status line: %s", err.Error())
	}

	responseHeaders := make(map[string]string)
	for {
		line, err := serverReader.ReadString('\n')
		if err != nil || line == "\r\n" {
			break
		}

		parts := strings.SplitN(line, ":", 2)
		if len(parts) != 2 {
			continue
		}

		key := strings.TrimSpace(parts[0])
		value := strings.TrimSpace(parts[1])
		responseHeaders[key] = value
	}

	responseContentLength := responseHeaders["Content-Length"]

	responseBuilder := strings.Builder{}
	if responseContentLength != "" {
		length := 0
		if _, err := fmt.Sscanf(responseContentLength, "%d", &length); err != nil {
			return "", nil, fmt.Errorf("invalid Content-Length header in response: %s", responseContentLength)
		}

		body := make([]byte, length)
		_, err := io.ReadFull(serverReader, body)
		if err != nil {
			return "", nil, fmt.Errorf("error reading response body: %s", err.Error())
		}

		responseBuilder.Write(body)
	} else {
		for {
			line, err := serverReader.ReadString('\n')
			if err != nil {
				if err == io.EOF {
					break
				}
				return "", nil, fmt.Errorf("error reading server response: %s", err.Error())
			}
			responseBuilder.WriteString(line)
		}
	}

	response := responseStatus
	for key, value := range responseHeaders {
		response += fmt.Sprintf("%s: %s\r\n", key, value)
	}
	response += "\r\n" + responseBuilder.String()

	return response, responseHeaders, nil
}
