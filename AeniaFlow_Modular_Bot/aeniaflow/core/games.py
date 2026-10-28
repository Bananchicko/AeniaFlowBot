from collections import Counter
import random

LINES = [(0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6)]


def winner(board, mark):
    return any(all(board[i] == mark for i in line) for line in LINES)


def bot_move(board):
    empties = [i for i, value in enumerate(board) if value == "⬜"]
    for mark in ("⭕", "❌"):
        for index in empties:
            copy = board[:]
            copy[index] = mark
            if winner(copy, mark):
                return index
    return 4 if 4 in empties else random.choice(empties)


def score_word(answer: str, guess: str) -> str:
    result = ["⬛"] * len(answer)
    remaining = Counter()
    for i, letter in enumerate(answer):
        if letter == guess[i]:
            result[i] = "🟩"
        else:
            remaining[letter] += 1
    for i, letter in enumerate(guess):
        if result[i] == "⬛" and remaining[letter]:
            result[i] = "🟨"
            remaining[letter] -= 1
    return "".join(result)
