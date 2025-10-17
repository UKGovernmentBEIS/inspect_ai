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

interface WorkQueueOptions {
  batchSize: number;
  processingDelay?: number;
  maxRetries?: number;
  onProcessingChanged?: (processing: boolean) => void;
}

export class WorkQueue<TInput, TOutput> {
  private queue: WorkItem<TInput>[] = [];
  private processing = false;
  private worker: ((items: TInput[]) => Promise<TOutput[]>) | null = null;
  private onComplete: ((results: TOutput[], inputs: TInput[]) => void) | null =
    null;
  private options: Required<WorkQueueOptions>;
  private backoffDelay = 0;
  private consecutiveErrors = 0;

  constructor(options: WorkQueueOptions) {
    this.options = {
      processingDelay: 100,
      maxRetries: 3,
      onProcessingChanged: (_processing: boolean) => {},
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
      retries: 0,
    }));

    // Deduplicate - don't add if already in queue
    const existingIds = new Set(this.queue.map((item) => item.id));
    const toAdd = newItems.filter((item) => !existingIds.has(item.id));

    // If the new item is higher priority than an existing one, update the existing one's priority
    for (const newItem of newItems) {
      const existingItem = this.queue.find((item) => item.id === newItem.id);
      if (existingItem && newItem.priority > existingItem.priority) {
        existingItem.priority = newItem.priority;
      }
    }

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
    this.startProcessing();
  }

  async atOnce(items: TInput[]) {
    if (!this.worker) return;

    const results = await this.worker(items);

    if (this.onComplete) {
      this.onComplete(results, items);
    }
  }

  private async startProcessing() {
    if (this.processing || !this.worker) return;

    this.processing = true;
    this.options.onProcessingChanged?.(true);

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

        // Reset backoff on success
        this.consecutiveErrors = 0;
        this.backoffDelay = 0;
      } catch (error) {
        console.error("Work queue processing error:", error);

        // Re-queue items that haven't exceeded max retries
        const itemsToRetry = batch.filter(
          (item) => item.retries < this.options.maxRetries,
        );
        if (itemsToRetry.length > 0) {
          // Increment retry count and add back to queue
          itemsToRetry.forEach((item) => item.retries++);
          this.queue.unshift(...itemsToRetry);
        }

        // Increase backoff: 1x, 2x, 4x, 8x, 16x (max) of processingDelay
        this.consecutiveErrors++;
        const multiplier = Math.min(
          Math.pow(2, this.consecutiveErrors - 1),
          16,
        );
        this.backoffDelay = multiplier * (this.options.processingDelay || 100);
      }

      // Delay between batches (either normal delay or backoff delay)
      if (this.queue.length > 0) {
        const delay = this.backoffDelay || this.options.processingDelay || 0;
        if (delay > 0) {
          await new Promise((resolve) => setTimeout(resolve, delay));
        }
      }
    }

    // If items were added during processing, restart
    if (this.queue.length > 0) {
      this.startProcessing();
    }

    this.options.onProcessingChanged?.(false);
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
