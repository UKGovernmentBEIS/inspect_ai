package main

import "sync"

type Cache struct {
	data  map[string]string
	mutex sync.RWMutex
}

func (c *Cache) Get(key string) (string, bool) {
	c.mutex.Lock()
	value, ok := c.data[key]
	c.mutex.Unlock()
	return value, ok
}

func (c *Cache) Set(key, value string) {
	c.mutex.Lock()
	c.data[key] = value
	c.mutex.Unlock()
}

func (c *Cache) Clear() {
	c.mutex.Lock()
	for k := range c.data {
		delete(c.data, k)
	}
	c.mutex.Unlock()
}
