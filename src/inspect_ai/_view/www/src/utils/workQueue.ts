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
  batchSize: number;
  processingDelay?: number;
  maxRetries?: number;
  getId: (item: TInput) => string;
  worker: (items: TInput[]) => Promise<TOutput[]>;
  onComplete: (results: TOutput[], inputs: TInput[]) => Promise<void>;
  onProcessingChanged?: (processing: boolean) => void;
}

export class WorkQueue<TInput, TOutput> {
  private itemsById = new Map<string, WorkItem<TInput>>();
  private processing = false;
  private consecutiveErrors = 0;
  private options: Required<WorkQueueOptions<TInput, TOutput>>;

  constructor(options: WorkQueueOptions<TInput, TOutput>) {
    this.options = {
      processingDelay: 100,
      maxRetries: 3,
      onProcessingChanged: (_processing: boolean) => {},
      ...options,
    };
  }

  enqueue(items: TInput[], priority: WorkPriority = WorkPriority.Medium) {
    const now = Date.now();

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
      }
    }

    void this.startProcessing();
  }

  async processImmediate(items: TInput[]) {
    const results = await this.options.worker(items);
    this.options.onComplete(results, items);
  }

  private async startProcessing() {
    if (this.processing) {
      return;
    }

    this.processing = true;

    try {
      this.options.onProcessingChanged(true);
    } catch (error) {
      console.error("onProcessingChanged callback error:", error);
    }

    try {
      while (this.itemsById.size > 0) {
        // Get next batch (sorted by priority, then age)
        const batch = this.getNextBatch();

        const inputs = batch.map((item) => item.data);

        try {
          const results = await this.options.worker(inputs);
          await this.options.onComplete(results, inputs);

          // Remove successful items
          batch.forEach((item) => this.itemsById.delete(item.id));
          this.consecutiveErrors = 0;
        } catch (error) {
          console.error("Work queue processing error:", error);

          // Retry or remove items
          for (const item of batch) {
            if (item.retries < this.options.maxRetries) {
              // Retry this item
              item.retries++;
            } else {
              // Item has been retried too many times, remove it
              this.itemsById.delete(item.id);
            }
          }

          this.consecutiveErrors++;
        }

        // Delay between batches
        if (this.itemsById.size > 0) {
          const delay = this.getBackoffDelay();
          if (delay > 0) {
            await new Promise((resolve) => setTimeout(resolve, delay));
          }
        }
      }
    } finally {
      this.processing = false;
      try {
        this.options.onProcessingChanged(false);
      } catch (error) {
        console.error("onProcessingChanged callback error:", error);
      }
    }
  }

  private getNextBatch(): WorkItem<TInput>[] {
    const items = Array.from(this.itemsById.values()).sort((a, b) => {
      if (a.priority !== b.priority) {
        // Higher priority first
        return b.priority - a.priority;
      }
      // Older first
      return a.addedAt - b.addedAt;
    });
    return items.slice(0, this.options.batchSize);
  }

  private getBackoffDelay(): number {
    if (this.consecutiveErrors === 0) {
      return this.options.processingDelay;
    }
    const multiplier = Math.min(Math.pow(2, this.consecutiveErrors - 1), 16);
    return multiplier * this.options.processingDelay;
  }

  clear() {
    this.itemsById.clear();
  }

  get size() {
    return this.itemsById.size;
  }

  get isProcessing() {
    return this.processing;
  }
}
