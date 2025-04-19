# Testing Structure

This directory contains the test files for the application. The test framework is built using Jest and TypeScript.

## Directory Structure

- `tests/`: Root directory for all tests
  - `__mocks__/`: Mock files for CSS modules and other assets
  - `setupTests.mjs`: Setup file for Jest tests

## Running Tests

To run the tests, use the following commands:

```bash
# Run all tests
yarn test

# Run tests in watch mode
yarn test:watch

# Run tests with coverage report
yarn test:coverage
```

## Test Philosophy

Tests are designed to verify functionality rather than implementation details. This means:

- Tests should not break due to minor changes in HTML structure
- Tests focus on the behavior of functions and components
- Tests should be fast and reliable

## Adding Tests

When adding new tests:

1. Create a new test file with the `.test.ts` or `.test.tsx` extension
2. Import the functions or components you want to test
3. Write tests that verify behavior without making assumptions about implementation
4. Use descriptive test names to make it clear what's being tested

## Mocking

For mocking external services or components:

1. Create mock files in the `__mocks__` directory
2. Mock only what's necessary for the test
3. Use Jest's mocking capabilities to replace dependencies
