// @ts-check
/**
 * Delays the execution of code for a specified number of milliseconds.
 *
 * @param {number} ms - The number of milliseconds to delay.
 * @returns {Promise<void>} - A promise that resolves after the specified delay.
 */
export function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Creates a throttled version of a function that only invokes the original function
 * at most once per every `wait` milliseconds. The throttled function will run as much
 * as it can, without ever going more than once per `wait` duration.
 *
 * @param {Function} func - The function to throttle.
 * @param {number} wait - The number of milliseconds to throttle executions to.
 * @param {Object} [options] - The options object.
 * @param {boolean} [options.leading=true] - If `false`, the function will not be invoked on the leading edge.
 * @param {boolean} [options.trailing=true] - If `false`, the function will not be invoked on the trailing edge.
 * @returns {Function} - The throttled function.
 */
export function throttle(func, wait, options) {
  var context, args, result;
  var timeout = null;
  var previous = 0;
  if (!options) options = {};
  var later = function () {
    previous = options.leading === false ? 0 : Date.now();
    timeout = null;
    result = func.apply(context, args);
    if (!timeout) context = args = null;
  };
  return function () {
    var now = Date.now();
    if (!previous && options.leading === false) previous = now;
    var remaining = wait - (now - previous);
    context = this;
    args = arguments;
    if (remaining <= 0 || remaining > wait) {
      if (timeout) {
        clearTimeout(timeout);
        timeout = null;
      }
      previous = now;
      result = func.apply(context, args);

      if (!timeout) context = args = null;
    } else if (!timeout && options.trailing !== false) {
      timeout = setTimeout(later, remaining);
    }
    return result;
  };
}

/**
 * Creates a debounced version of a function that delays invoking the function
 * until after `wait` milliseconds have passed since the last time it was invoked.
 *
 * @param {Function} func - The function to debounce.
 * @param {number} wait - The number of milliseconds to delay.
 * @param {Object} [options] - The options object.
 * @param {boolean} [options.leading=false] - If `true`, the function will be invoked on the leading edge of the timeout.
 * @param {boolean} [options.trailing=true] - If `false`, the function will not be invoked on the trailing edge.
 * @returns {Function} - The debounced function.
 */
export function debounce(func, wait, options = {}) {
  let timeout, context, args, result;
  let lastCallTime = null;

  const later = () => {
    const last = Date.now() - lastCallTime;
    if (last < wait && last >= 0) {
      timeout = setTimeout(later, wait - last);
    } else {
      timeout = null;
      if (!options.leading) {
        result = func.apply(context, args);
        if (!timeout) context = args = null;
      }
    }
  };

  return function () {
    context = this;
    args = arguments;
    lastCallTime = Date.now();

    const callNow = options.leading && !timeout;
    if (!timeout) {
      timeout = setTimeout(later, wait);
    }
    if (callNow) {
      result = func.apply(context, args);
      context = args = null;
    }

    return result;
  };
}
