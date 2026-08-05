// Kimo Robot Pet — Arduino Motor Controller
// Receives serial commands from Raspberry Pi and drives 4WD chassis via L298N

// --- Pin Definitions ---
// Channel A → Left motors
#define ENA 9   // PWM speed control
#define IN1 2
#define IN2 3

// Channel B → Right motors
#define ENB 10  // PWM speed control
#define IN3 4
#define IN4 5

#define MOTOR_SPEED 200  // 0-255 PWM

void setup() {
  Serial.begin(9600);

  pinMode(ENA, OUTPUT);
  pinMode(IN1, OUTPUT);
  pinMode(IN2, OUTPUT);
  pinMode(ENB, OUTPUT);
  pinMode(IN3, OUTPUT);
  pinMode(IN4, OUTPUT);

  stopMotors();
  Serial.println("KIMO READY");
}

void loop() {
  if (Serial.available() > 0) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();

    if      (cmd == "FORWARD")  forward();
    else if (cmd == "BACKWARD") backward();
    else if (cmd == "LEFT")     turnLeft();
    else if (cmd == "RIGHT")    turnRight();
    else if (cmd == "STOP")     stopMotors();
    else if (cmd == "DANCE")    dance();
  }
}

// --- Motor Functions ---

void forward() {
  digitalWrite(IN1, LOW); digitalWrite(IN2, HIGH);   // Left forward
  digitalWrite(IN3, LOW); digitalWrite(IN4, HIGH);   // Right forward
  analogWrite(ENA, MOTOR_SPEED);
  analogWrite(ENB, MOTOR_SPEED);
}

void backward() {
  digitalWrite(IN1, HIGH); digitalWrite(IN2, LOW);   // Left backward
  digitalWrite(IN3, HIGH); digitalWrite(IN4, LOW);   // Right backward
  analogWrite(ENA, MOTOR_SPEED);
  analogWrite(ENB, MOTOR_SPEED);
}

void turnLeft() {
  // Spin in place: left backward, right forward
  digitalWrite(IN1, HIGH); digitalWrite(IN2, LOW);
  digitalWrite(IN3, LOW); digitalWrite(IN4, HIGH);
  analogWrite(ENA, MOTOR_SPEED);
  analogWrite(ENB, MOTOR_SPEED);
}

void turnRight() {
  // Spin in place: left forward, right backward
  digitalWrite(IN1, LOW); digitalWrite(IN2, HIGH);
  digitalWrite(IN3, HIGH); digitalWrite(IN4, LOW);
  analogWrite(ENA, MOTOR_SPEED);
  analogWrite(ENB, MOTOR_SPEED);
}

void stopMotors() {
  digitalWrite(IN1, LOW); digitalWrite(IN2, LOW);
  digitalWrite(IN3, LOW); digitalWrite(IN4, LOW);
  analogWrite(ENA, 0);
  analogWrite(ENB, 0);
}

void dance() {
  // Full 360° spins
  turnRight(); delay(800);   // spin right ~360°
  turnLeft();  delay(800);   // spin left ~360°

  // Frantic giggles (3x original)
  for (int i = 0; i < 12; i++) {
    turnLeft();  delay(300);
    turnRight(); delay(300);
  }
  stopMotors();
}
