/**
 * A class that manages asynchronous task execution with a limit on concurrent tasks.
 */
export class AsyncQueue {
  constructor(concurrentLimit: number = 6) {
    this.concurrentLimit = concurrentLimit;
    this.queue = [];
    this.runningCount = 0;
  }

  // Max concurrency
  private readonly concurrentLimit: number;

  // The queue
  private readonly queue: Array<() => Promise<void>>;

  // Count of currently running tasks
  private runningCount: number;

  // Adds a task to the queue and runs it if the concurrency limit allows.
  async enqueue<T>(task: () => Promise<T>): Promise<T> {
    return new Promise<T>((resolve, reject) => {
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

  // Runs the next task in the queue if there are available slots for concurrent execution.
  private runNext(): void {
    if (this.queue.length > 0 && this.runningCount < this.concurrentLimit) {
      const task = this.queue.shift();
      if (task) {
        this.runningCount++;
        task();
      }
    }
  }
}
