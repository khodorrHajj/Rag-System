export type SignUpPayload = {
  email: string;
  password: string;
  firstName: string;
  lastName: string;
  phoneNumber: string;
};

function digitsOnly(value: string): string {
  return value.replace(/\D/g, "");
}

export function buildFullName(firstName: string, lastName: string): string {
  return `${firstName.trim()} ${lastName.trim()}`.trim();
}

export function normalizeLebanesePhone(rawValue: string): string | null {
  const trimmed = rawValue.trim();
  if (!trimmed) {
    return null;
  }

  if (trimmed.startsWith("+")) {
    const digits = digitsOnly(trimmed.slice(1));
    if (!digits.startsWith("961")) {
      return null;
    }

    const localNumber = digits.slice(3);
    if (!/^\d{7,8}$/.test(localNumber)) {
      return null;
    }

    return `+961${localNumber}`;
  }

  const digits = digitsOnly(trimmed);
  let localNumber = digits;

  if (digits.startsWith("00961")) {
    localNumber = digits.slice(5);
  } else if (digits.startsWith("961")) {
    localNumber = digits.slice(3);
  } else if (digits.startsWith("0")) {
    localNumber = digits.slice(1);
  }

  if (!/^\d{7,8}$/.test(localNumber)) {
    return null;
  }

  return `+961${localNumber}`;
}

export function validateSignUpPayload(payload: SignUpPayload): string | null {
  if (!payload.firstName.trim()) {
    return "First name is required.";
  }

  if (!payload.lastName.trim()) {
    return "Last name is required.";
  }

  if (!normalizeLebanesePhone(payload.phoneNumber)) {
    return "Enter a valid Lebanese phone number. Example: +961 71 123 456 or 03 123 456.";
  }

  if (payload.password.length < 8) {
    return "Password must be at least 8 characters.";
  }

  return null;
}

export function toFriendlyAuthError(rawMessage: string): string {
  const normalizedMessage = rawMessage.trim().toLowerCase();

  if (normalizedMessage.includes("email rate limit exceeded")) {
    return "Too many confirmation emails were requested recently. Wait a few minutes, then try again or confirm the existing signup email first.";
  }

  if (normalizedMessage.includes("email address") && normalizedMessage.includes("is invalid")) {
    return "Enter a real email address that can receive the confirmation message.";
  }

  if (normalizedMessage.includes("user already registered")) {
    return "An account with this email already exists. Sign in instead, or confirm the existing signup email.";
  }

  if (normalizedMessage.includes("email not confirmed")) {
    return "Email confirmation is enabled for this project. Open the confirmation email before signing in.";
  }

  if (normalizedMessage.includes("database error saving new user")) {
    return "We couldn't finish creating the account. If that Lebanese phone number is already in use, try a different one.";
  }

  return rawMessage;
}
