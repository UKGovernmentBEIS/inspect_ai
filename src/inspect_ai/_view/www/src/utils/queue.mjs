/**
 * A class that manages asynchronous task execution with a limit on concurrent tasks.
 */
export class AsyncQueue {
  /**
   * Creates an instance of AsyncQueue.
   * @param {number} [concurrentLimit=6] - The maximum number of tasks that can run concurrently.
   */
  constructor(concurrentLimit = 6) {
    /**
     * The maximum number of concurrent tasks.
     * @type {number}
     */
    this.concurrentLimit = concurrentLimit;

    /**
     * The queue of tasks waiting to be executed.
     * @type {Array<Function>}
     */
    this.queue = [];

    /**
     * The count of currently running tasks.
     * @type {number}
     */
    this.runningCount = 0;
  }

  /**
   * Adds a task to the queue and runs it if the concurrency limit allows.
   * @param {Function} task - The task to be executed asynchronously. This should be a function that returns a promise.
   * @returns {Promise<*>} - A promise that resolves with the result of the task or rejects if the task throws an error.
   */
  async enqueue(task) {
    return new Promise((resolve, reject) => {
      this.queue.push(async () => {
        try {
          const result = await task();
          resolve(result);
        } catch (error) {
          reject(error);
        } finally {
          this.runningCount--;
          this.runNext();
        }
      });

      if (this.runningCount < this.concurrentLimit) {
        this.runNext();
      }
    });
  }

  /**
   * Runs the next task in the queue if there are available slots for concurrent execution.
   * @private
   */
  runNext() {
    if (this.queue.length > 0 && this.runningCount < this.concurrentLimit) {
      const task = this.queue.shift();
      if (task) {
        this.runningCount++;
        task();
      }
    }
  }
}
