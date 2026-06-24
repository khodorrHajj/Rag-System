import { useState } from "react";

import type { FeedbackRecord, FeedbackRating } from "../types/api";

type MessageFeedbackProps = {
  feedback?: FeedbackRecord;
  loading?: boolean;
  onSubmit: (rating: FeedbackRating, comment?: string) => Promise<void>;
};

export function MessageFeedback({
  feedback,
  loading = false,
  onSubmit,
}: MessageFeedbackProps) {
  const [showNegativeForm, setShowNegativeForm] = useState(false);
  const [comment, setComment] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);

  async function handlePositiveClick() {
    setLocalError(null);
    try {
      await onSubmit("positive");
    } catch (error) {
      setLocalError(
        error instanceof Error ? error.message : "Could not save feedback right now.",
      );
    }
  }

  async function handleNegativeSubmit() {
    setLocalError(null);
    try {
      await onSubmit("negative", comment.trim() || undefined);
      setShowNegativeForm(false);
      setComment("");
    } catch (error) {
      setLocalError(
        error instanceof Error ? error.message : "Could not save feedback right now.",
      );
    }
  }

  return (
    <div className="message-feedback">
      <div className="message-feedback__row">
        <span className="message-feedback__label">Was this answer helpful?</span>
        <button
          className={`button button--feedback ${feedback?.rating === "positive" ? "button--feedback-active" : ""}`}
          disabled={loading || Boolean(feedback)}
          onClick={() => void handlePositiveClick()}
          type="button"
        >
          Helpful
        </button>
        <button
          className={`button button--feedback ${feedback?.rating === "negative" ? "button--feedback-active" : ""}`}
          disabled={loading || Boolean(feedback)}
          onClick={() => setShowNegativeForm(true)}
          type="button"
        >
          Needs work
        </button>
        {feedback ? (
          <span className="message-feedback__status">
            Feedback saved
          </span>
        ) : null}
      </div>

      {feedback?.rating === "negative" && feedback.comment ? (
        <p className="message-feedback__comment">Comment: {feedback.comment}</p>
      ) : null}

      {!feedback && showNegativeForm ? (
        <div className="message-feedback__composer">
          <textarea
            maxLength={500}
            onChange={(event) => setComment(event.target.value)}
            placeholder="Optional: tell us what was missing or incorrect."
            rows={3}
            value={comment}
          />
          <div className="message-feedback__actions">
            <button
              className="button button--ghost"
              disabled={loading}
              onClick={() => {
                setShowNegativeForm(false);
                setComment("");
                setLocalError(null);
              }}
              type="button"
            >
              Cancel
            </button>
            <button
              className="button button--primary"
              disabled={loading}
              onClick={() => void handleNegativeSubmit()}
              type="button"
            >
              {loading ? "Saving..." : "Submit feedback"}
            </button>
          </div>
          {localError ? <p className="inline-detail inline-detail--danger">{localError}</p> : null}
        </div>
      ) : null}
    </div>
  );
}
