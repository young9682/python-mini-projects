import random
number = random.randint(1, 100)
time = 0
print("Welcome to the 'Guess the Number' game!")
print("This time you will have 10 attempts to guess the number between 1 and 100.")
while time < 10:
    guess = int(input("Please enter your guess (between 1 and 100): "))
    time += 1
    if guess < number:
        print("Your guess is too low.")
    elif guess > number:
        print("Your guess is too high.")
    else:
        print(f"Congratulations! You've guessed the number {number} in {time} attempts.")
        break
else:
    print(f"Sorry, you've used all 10 attempts. The number was {number}.")