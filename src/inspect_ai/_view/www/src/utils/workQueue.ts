export enum WorkPriority {
  Low = 0,
  Medium = 1,
  High = 2,
}

interface WorkItem<T> {
  id: string;
  data: T;
  priority: WorkPriority;
  addedAt: number;
  retries: number;
}

interface WorkQueueOptions<TInput, TOutput> {
  name: string;
  concurrency: number;
  batchSize?: number;
  processingDelay?: number;
  maxRetries?: number;
  getId: (item: TInput) => string;
  worker: (items: TInput[]) => Promise<TOutput[]>;
  onComplete: (results: TOutput[], inputs: TInput[]) => Promise<void>;
  onProcessingChanged?: (processing: boolean) => void;
}

export class WorkQueue<TInput, TOutput> {
  private itemsById = new Map<string, WorkItem<TInput>>();
  private activeWorkers = 0;
  private options: Required<WorkQueueOptions<TInput, TOutput>>;

  constructor(options: WorkQueueOptions<TInput, TOutput>) {
    this.options = {
      batchSize: 1,
      processingDelay: 100,
      maxRetries: 3,
      onProcessingChanged: (_processing: boolean) => {},
      ...options,
    };
  }

  enqueue(items: TInput[], priority: WorkPriority = WorkPriority.Medium) {
    const now = Date.now();

    let newItemsCount = 0;
    for (const item of items) {
      const id = this.options.getId(item);
      const existing = this.itemsById.get(id);

      if (existing) {
        // Update priority if higher
        if (priority > existing.priority) {
          existing.priority = priority;
        }
      } else {
        // Add new item
        this.itemsById.set(id, {
          id,
          data: item,
          priority,
          addedAt: now,
          retries: 0,
        });
        newItemsCount++;
      }
    }
    void this.startProcessing();
  }

  async processImmediate(items: TInput[]) {
    const results = await this.options.worker(items);
    this.options.onComplete(results, items);
  }

  private async startProcessing() {
    // Start new workers up to concurrency limit
    while (
      this.activeWorkers < this.options.concurrency &&
      this.itemsById.size > 0
    ) {
      this.activeWorkers++;

      // The first worker to start triggers the processing changed callback
      if (this.activeWorkers === 1) {
        try {
          this.options.onProcessingChanged(true);
        } catch (error) {
          console.error("onProcessingChanged callback error:", error);
        }
      }

      // Run the worker
      void this.runWorker();
    }
  }

  private async runWorker() {
    try {
      while (this.itemsById.size > 0) {
        // Get next batch (sorted by priority, then age) and remove from queue immediately
        const batch = this.claimNextBatch();

        // No work, audi 5000
        if (batch.length === 0) {
          break;
        }

        const inputs = batch.map((item) => item.data);

        try {
          const results = await this.options.worker(inputs);

          this.options.onComplete(results, inputs);
        } catch (error) {
          console.error("Work queue processing error:", error);

          // Retry or remove items
          for (const item of batch) {
            if (item.retries < this.options.maxRetries) {
              // Retry this item - add it back to the queue
              item.retries++;
              this.itemsById.set(item.id, item);
            }
            // Otherwise item is just dropped (already removed from queue)
          }
        }

        // Delay between batches
        if (this.itemsById.size > 0 && this.options.processingDelay > 0) {
          await new Promise((resolve) =>
            setTimeout(resolve, this.options.processingDelay),
          );
        }
      }
    } finally {
      // This worker is stopping
      this.activeWorkers--;

      if (this.activeWorkers === 0) {
        try {
          this.options.onProcessingChanged(false);
        } catch (error) {
          console.error("onProcessingChanged callback error:", error);
        }
      }
    }
  }

  private claimNextBatch(): WorkItem<TInput>[] {
    // Fetch the highest priority, oldest items
    const items = Array.from(this.itemsById.values()).sort((a, b) => {
      if (a.priority !== b.priority) {
        // Higher priority first
        return b.priority - a.priority;
      }
      // Older first
      return a.addedAt - b.addedAt;
    });

    // Slice into a batch
    const batch = items.slice(0, this.options.batchSize);

    // Remove claimed items from the queue immediately
    batch.forEach((item) => this.itemsById.delete(item.id));
    return batch;
  }

  clear() {
    this.itemsById.clear();
  }

  get size() {
    return this.itemsById.size;
  }

  get isProcessing() {
    return this.activeWorkers > 0;
  }
}
