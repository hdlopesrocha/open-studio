'use strict';

class HttpError extends Error {
  constructor(status, message, details) {
    super(message);
    this.name = 'HttpError';
    this.status = status;
    if (details !== undefined) this.details = details;
  }
}

class JobCancelled extends Error {
  constructor(message = 'Cancelled by the user') {
    super(message);
    this.name = 'JobCancelled';
    this.cancelled = true;
  }
}

module.exports = { HttpError, JobCancelled };
