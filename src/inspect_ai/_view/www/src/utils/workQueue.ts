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
}

interface WorkQueueOptions {
  batchSize: number;
  processingDelay?: number;
  maxRetries?: number;
}

export class WorkQueue<TInput, TOutput> {
  private queue: WorkItem<TInput>[] = [];
  private processing = false;
  private worker: ((items: TInput[]) => Promise<TOutput[]>) | null = null;
  private onComplete: ((results: TOutput[], inputs: TInput[]) => void) | null =
    null;
  private options: Required<WorkQueueOptions>;

  constructor(options: WorkQueueOptions) {
    this.options = {
      processingDelay: 100,
      maxRetries: 3,
      ...options,
    };
  }

  setWorker(worker: (items: TInput[]) => Promise<TOutput[]>) {
    this.worker = worker;
  }

  setOnComplete(callback: (results: TOutput[], inputs: TInput[]) => void) {
    this.onComplete = callback;
  }

  enqueue(
    items: TInput[],
    getId: (item: TInput) => string,
    priority: WorkPriority = WorkPriority.Medium,
  ) {
    const now = Date.now();
    const newItems = items.map((item) => ({
      id: getId(item),
      data: item,
      priority,
      addedAt: now,
    }));

    // Deduplicate - don't add if already in queue
    const existingIds = new Set(this.queue.map((item) => item.id));
    const toAdd = newItems.filter((item) => !existingIds.has(item.id));

    this.queue.push(...toAdd);

    // Sort queue by priority (high to low), then by addedAt (oldest first)
    this.queue.sort((a, b) => {
      if (a.priority !== b.priority) {
        // Higher priority first
        return b.priority - a.priority;
      }
      // Older first
      return a.addedAt - b.addedAt;
    });

    // Start processing if not already running
    if (!this.processing) {
      this.startProcessing();
    }
  }

  private async startProcessing() {
    if (this.processing || !this.worker) return;

    this.processing = true;

    while (this.queue.length > 0) {
      // Get next batch
      const batch = this.queue.splice(0, this.options.batchSize);
      const inputs = batch.map((item) => item.data);

      try {
        const results = await this.worker(inputs);

        // Notify completion
        if (this.onComplete) {
          this.onComplete(results, inputs);
        }
      } catch (error) {
        // TODO: Retry?
        console.error("Work queue processing error:", error);
      }

      // Delay between batches
      if (this.queue.length > 0 && this.options.processingDelay) {
        await new Promise((resolve) =>
          setTimeout(resolve, this.options.processingDelay),
        );
      }
    }

    this.processing = false;
  }

  clear() {
    this.queue = [];
  }

  get size() {
    return this.queue.length;
  }

  get isProcessing() {
    return this.processing;
  }
}
