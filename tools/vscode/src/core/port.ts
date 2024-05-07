import { Socket, createServer } from "net";
import { randomInt } from "./random";

const kLocalhost = "127.0.0.1";
const kMinPort = 3000;
const kMaxPort = 8000;

export async function findOpenPort(defaultPort?: number): Promise<number> {
  defaultPort = defaultPort || randomSafePort();

  const available = await isPortAvailable(defaultPort, kLocalhost);
  if (available) {
    return defaultPort;
  } else {
    do {
      defaultPort++;
    } while (!isPortSafe(defaultPort));
    return findOpenPort(defaultPort);
  }
}

function randomSafePort(): number {
  let result: number;
  do {
    result = randomInt(kMinPort, kMaxPort);
  } while (!isPortSafe(result));
  return result;
}

interface ServerError extends Error {
  code?: string;
}

export async function isPortAvailable(port: number, hostName: string) {
  return !(await listen(port, hostName));
}

async function listen(port: number, hostName: string): Promise<boolean> {

    // First check the socket
    const socketInUse = await checkSocket(port, hostName);
    if (socketInUse) {
      return true;
    }


    return await isServerListening(port, hostName);
}

export async function isServerListening(port: number, hostName: string) : Promise<boolean> {
  const server = createServer();
  return new Promise((resolve, reject) => {

    server.listen(port, hostName);
    server.on("listening", () => {
      console.log(`Server listening on ${hostName}:${port}`);
      server.close(() => {
        server.removeAllListeners();
        resolve(false);
      });
    });  
    server.on("error", (err: ServerError) => {
      console.log(`Server error: ${err.code}`);
      if (err.code === "EADDRINUSE") {
        resolve(true);
      } else {
        reject(err);
      }
    });
  });

}
 
function checkSocket(port: number, hostName: string) {
    return new Promise((resolve, reject) => {
      const client = new Socket();
  
      client.once('connect', () => {
        client.destroy();
        resolve(true); // Port is in use
      });
  
      client.once('error', (err: ServerError) => {
        client.destroy();
        if (err.code === 'ECONNREFUSED') {
          resolve(false); // Port is not in use
        } else {
          reject(err); // Some other error occurred
        }
      });
  
      client.connect(port, hostName);
    });
  }

function isPortSafe(port: number): boolean {
  // https://superuser.com/a/188070
  // excludes port numbers that chrome considers unsafe
  return ![
    3659, // apple-sasl / PasswordServer
    4045, // lockd
    5060, // sip
    5061, // sips
    6000, // X11
    6566, // sane-port
    6665, // Alternate IRC [Apple addition]
    6666, // Alternate IRC [Apple addition]
    6667, // Standard IRC [Apple addition]
    6668, // Alternate IRC [Apple addition]
    6669, // Alternate IRC [Apple addition]
    6697, // IRC + TLS
  ].includes(port);
}
