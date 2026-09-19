import { AnimatedSignIn } from "./ui/sign-in";

export default function LoginPage({ onLogin }) {
  return <AnimatedSignIn onLogin={onLogin} />;
}
