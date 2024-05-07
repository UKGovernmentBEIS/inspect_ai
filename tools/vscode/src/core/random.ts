


export function randomInt(min: number, max: number) {
    min = Math.ceil(min);
    max = Math.floor(max);
    return Math.floor(cryptoRandom() * (max - min) + min);
  }
  

  // version of Math.random() that uses web crypto
// https://stackoverflow.com/questions/13694626/generating-random-numbers-0-to-1-with-crypto-generatevalues
export function cryptoRandom() {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const crypto = require('crypto') as { getRandomValues: (arr: Uint32Array) => void; };
    
    const arr = new Uint32Array(2);
    crypto.getRandomValues(arr);
  
    // keep all 32 bits of the the first, top 20 of the second for 52 random bits
    const mantissa = (arr[0] * Math.pow(2, 20)) + (arr[1] >>> 12);
  
    // shift all 52 bits to the right of the decimal point
    const result = mantissa * Math.pow(2, -52);
    return result;
  }
  