# Simple HMM implementation. Test code focuses on discrete signal reconstruction.

import sys
import random
from itertools import izip, islice
from time import time
from math import log, exp

from countermap import CounterMap
from nlp import counter as Counter
from penntreebankreader import PennTreebankReader

START_LABEL = "<START>"
STOP_LABEL = "<STOP>"

class HiddenMarkovModel:
	# Distribution over next state given current state
	labels = list()
	transition = CounterMap()
	reverse_transition = CounterMap() # same as transitions but indexed in reverse (useful for decoding)

	# Multinomial distribution over emissions given label
	emission = CounterMap()
	# p(label | emission)
	label_emissions = CounterMap()

	def __pad_sequence(self, sequence, pairs=False):
		if pairs: padding = [(START_LABEL, START_LABEL),]
		else: padding = [START_LABEL,]
		padding.extend(sequence)
		if pairs: padding.append((STOP_LABEL, STOP_LABEL))
		else: padding.append(STOP_LABEL)

		return padding

	def train(self, labeled_sequence):
		label_counts = Counter()
		# Currently this assumes the HMM is multinomial
		last_label = None

		labeled_sequence = self.__pad_sequence(labeled_sequence, pairs=True)

		# Transitions
		for label, emission in labeled_sequence:
			label_counts[label] += 1.0
			self.emission[label][emission] += 1.0
			self.label_emissions[emission][label] += 1.0
			if last_label:
				self.transition[last_label][label] += 1.0
			last_label = label

		self.label_emissions.normalize()
		self.transition.normalize()
		self.emission.normalize()
		self.labels = self.emission.keys()

		uniform = 1.0 / float(len(self.labels))
		epsilon = 0.00001

		# Small smoothing factor for label transitions
		for label in self.labels:
			if label not in self.transition:
				for next_label in self.labels:
					self.transition[label][next_label] = uniform
			elif label == STOP_LABEL:
				continue
			else:
				for next_label in self.labels:
					if next_label == START_LABEL:
						continue
					if next_label not in self.transition[label]:
						self.transition[label][next_label] = epsilon
				self.transition[label].normalize()

		# Convert to log score counters
		for counter_map in (self.label_emissions, self.transition, self.emission):
			for key, sub_counter in counter_map.iteritems():
				for sub_key, score in sub_counter.iteritems():
					counter_map[key][sub_key] = log(score)
				sub_counter.default = float("-inf")

		# Construct reverse transition probabilities
		for label, counter in self.transition.iteritems():
			for sublabel, score in counter.iteritems():
				self.reverse_transition[sublabel][label] = score
				self.reverse_transition[sublabel].default = float("-inf")

	def fallback_probs(self, emission):
		fallback = Counter()
		uniform = log(1.0 / len(self.labels))
		for label in self.labels: fallback[label] = uniform

		return fallback

	def score(self, labeled_sequence, debug=False):
		score = 0.0
		last_label = START_LABEL

		if debug: print "*** SCORE (%s) ***" % labeled_sequence

		for pos, (label, emission) in enumerate(labeled_sequence):
			if emission in self.emission[label]:
				score += self.emission[label][emission]
			else:
				score += self.fallback_probs(emission)[label]
			score += self.transition[last_label][label]
			last_label = label
			if debug: print "  SCP %d score after label %s emits %s: %s" % (pos, label, emission, score)

		score += self.transition[last_label][STOP_LABEL]

		if debug: print "*** SCORE => %f ***" % score
		
		return score

	def label(self, emission_sequence, debug=False, start_at=0):
		print emission_sequence
		# This needs to perform viterbi decoding on the the emission sequence
		emission_sequence = self.__pad_sequence(emission_sequence)

		# Backtracking pointers - backtrack[position] = {state : prev, ...}
		backtrack = [dict() for state in emission_sequence]

		# Scores are indexed by pos - 1 in the padded sequence(so we can initialize it with uniform probability, or the stationary if we have it)
		scores = [Counter() for state in emission_sequence]
		for counter in scores: counter.default = float("-inf")

		# Start is hardcoded
		for label in self.labels: scores[0][label] = float("-inf")
		scores[0][START_LABEL] = 0.0
		end = len(emission_sequence)-2

		last_min = 0.0

		if start_at > 0:
			debug = False

		for pos, emission in enumerate(emission_sequence[1:]):
			if debug: print "*** POS %d: EMISSION %s ***" % (pos, emission)
			if debug: print "  Scores coming in to %d: %s" % (pos, scores[pos])

			# At each position calculate the transition scores and the emission probabilities (independent given the state!)
			if emission in self.label_emissions:
				emission_probs = self.label_emissions[emission]
				if debug: print "  Observed emission %s" % (emission)
			else:
				emission_probs = self.fallback_probs(emission)
				if debug: print "  Fallback on emission %s" % (emission)

			# scores[pos+1] = max(scores[pos][label] * transitions[label][nextlabel] for label, nextlabel)
			# backtrack = argmax(^^)
			for label in self.labels:
				if emission_probs[label] == float("-inf"): continue
				if debug: print "  Label %s" % label
				if pos != end and label == STOP_LABEL or label == START_LABEL:
					scores[pos+1][label] = float("-inf")
					continue
				transition_scores = scores[pos] + self.reverse_transition[label]
				print transition_scores
				arg_max = transition_scores.arg_max()
				backtrack[pos][label] = arg_max
				transition_scores += emission_probs[label]
#				if debug: print "    Reverse transition scores: %s" % self.reverse_transition[label]
				if debug: print "    Emission probs: %s" % exp(emission_probs[label])
				scores[pos+1][label] = transition_scores[arg_max]

			if debug: print "  Backtrack to %d: %s" % (pos, backtrack[pos])
			if start_at > 0 and start_at == pos: debug = True


		if debug: print "Scores @ %d: %s" % (pos+1, scores[pos+1])

		# Now decode
		states = list()
		current = STOP_LABEL
		for pos in xrange(len(backtrack)-2, 0, -1):
			print "trying backtrack @ %d on label %s" % (pos, current)
			print "backtrack[pos] = %s" % backtrack[pos]
			current = backtrack[pos][current]
			states.append(current)

		states.reverse()
		return states

	def __sample_transition(self, label):
		sample = random.random()

		for next, prob in self.transition[label].iteritems():
			sample -= exp(prob)
			if sample <= 0.0: return next

		assert False, "Should have returned a next state"

	def __sample_emission(self, label):
		if label in [START_LABEL, STOP_LABEL]: return label
		sample = random.random()

		for next, prob in self.emission[label].iteritems():
			sample -= exp(prob)
			if sample <= 0.0: return next

		assert False, "Should have returned an emission"

	def sample(self, start=None):
		"""Returns a generator yielding a sequence of (state, emission) pairs
		generated by the modeled sequence"""
		state = start
		if not state:
			state = random.choice(self.transition.keys())
			for i in xrange(1000): state = self.__sample_transition(state)

		while True:
			yield (state, self.__sample_emission(state))
			state = self.__sample_transition(state)

def debug_problem(args):
	# Very simple chain for debugging purposes
	states = ['1', '1', '1', '2', '3', '3', '3', '3', STOP_LABEL, START_LABEL, '2', '3', '3']
	emissions = ['y', 'm', 'y', 'm', 'n', 'm', 'n', 'm', STOP_LABEL, START_LABEL, 'm', 'n', 'n']

	test_emissions = [['y', 'y', 'y', 'm', 'n', 'm', 'n', 'm'], ['y', 'm', 'n'], ['m', 'n', 'n', 'n']]
	test_labels = [['1', '1', '1', '2', '3', '3', '3', '3'], ['1', '2', '3'], ['2', '3', '3', '3']]

#	test_emissions, test_labels = ([['m', 'n', 'n', 'n']], [['2', '3', '3', '3']])

	chain = HiddenMarkovModel()
	chain.train(zip(states, emissions))

	print "Label"
	for emissions, labels in zip(test_emissions, test_labels):
		guessed_labels = chain.label(emissions)
		if guessed_labels != labels:
			print "Guessed: %s (score %f)" % (guessed_labels, chain.score(zip(guessed_labels, emissions)))
			print "Correct: %s (score %f)" % (labels, chain.score(zip(labels, emissions)))
			assert chain.score(zip(guessed_labels, emissions)) > chain.score(zip(labels, emissions)), "Decoder sub-optimality"
	print "Transition"
	print chain.transition
	print "Emission"
	print chain.emission

	sample = [val for _, val in izip(xrange(10), chain.sample())]
	print [label for label, _ in sample]
	print [emission for _, emission in sample]

def toy_problem(args):
	# Simulate a 3 state markov chain with transition matrix (given states in row vector):
	#  (destination)
	#   1    2    3
	# 1 0.7  0.3  0
	# 2 0.05 0.4  0.55
	# 3 0.25 0.25 0.5
	transitions = CounterMap()

	transitions['1']['1'] = 0.7
	transitions['1']['2'] = 0.3
	transitions['1']['3'] = 0.0

	transitions['2']['1'] = 0.05
	transitions['2']['2'] = 0.4
	transitions['2']['3'] = 0.55

	transitions['3']['1'] = 0.25
	transitions['3']['2'] = 0.25
	transitions['3']['3'] = 0.5

	def sample_transition(label):
		sample = random.random()

		for next, prob in transitions[label].iteritems():
			sample -= prob
			if sample <= 0.0: return next

		assert False, "Should have returned a next state"

	# And emissions (state, (counter distribution)): {1 : (yes : 0.5, sure : 0.5), 2 : (maybe : 0.75, who_knows : 0.25), 3 : (no : 1)}
	emissions = {'1' : {'yes' : 0.5, 'sure' : 0.5}, '2' : {'maybe' : 0.75, 'who_knows' : 0.25}, '3' : {'no' : 1.0}}

	def sample_emission(label):
		if label in [START_LABEL, STOP_LABEL]: return label
		choice = random.random()

		for emission, prob in emissions[label].iteritems():
			choice -= prob
			if choice <= 0.0: return emission

		assert False, "Should have returned an emission"
	
	# Create the training/test data
	states = ['1', '2', '3']
	start = random.choice(states)

	# Burn-in (easier than hand-calculating stationary distribution & sampling)
	for i in xrange(10000):	start = sample_transition(start)

	def label_generator(start_label):
		next = start_label
		while True:
			yield next
			next = sample_transition(next)

	training_labels = [val for _, val in izip(xrange(1000), label_generator('1'))]
	training_labels.extend((START_LABEL, STOP_LABEL))
	training_labels.extend([val for _, val in izip(xrange(1000), label_generator('2'))])
	training_labels.extend((START_LABEL, STOP_LABEL))
	training_labels.extend([val for _, val in izip(xrange(1000), label_generator('3'))])

	training_emissions = [sample_emission(label) for label in training_labels]

	training_signal = zip(training_labels, training_emissions)

	# Training phase
	signal_decoder = HiddenMarkovModel()
	signal_decoder.train(training_signal)

	# Labeling phase: given a set of emissions, guess the correct states
	start = random.choice(states)
	for i in xrange(10000):	start = sample_transition(start)
	test_labels = [val for _, val in izip(xrange(500), label_generator(start))]
	test_emissions = [sample_emission(label) for label in training_labels]

	guessed_labels = signal_decoder.label(test_emissions)
	correct = sum(1 for guessed, correct in izip(guessed_labels, test_labels) if guessed == correct)

	print "%d labels recovered correctly (%.2f%% correct out of %d)" % (correct, 100.0 * float(correct) / float(len(test_labels)), len(test_labels))


def merge_stream(stream):
	# Combine sentences into one long string, with each sentence start with <START> and ending with <STOP>
	# [1:-2] cuts the leading STOP_LABEL and the trailing START_LABEL
	sentences = []
	tag_stream = []
	for tags, sentence in stream:
		sentences.append(START_LABEL)
		tag_stream.append(START_LABEL)
		for word in sentence:
			sentences.append(word)
		for tag in tags:
			tag_stream.append(tag)
		sentences.append(STOP_LABEL)
		tag_stream.append(STOP_LABEL)

	return zip(tag_stream, sentences)

def pos_problem(args):
	dataset_size = None
	if len(args) > 0: dataset_size = int(args[0])
	# Load the dataset
	print "Loading dataset"
	start = time()
	if dataset_size: tagged_sentences = list(islice(PennTreebankReader.read_pos_tags_from_directory("data/wsj"), dataset_size))
	else: tagged_sentences = list(PennTreebankReader.read_pos_tags_from_directory("data/wsj"))
	stop = time()
	print "Reading: %f" % (stop-start)

	print "Creating streams"
	start = time()
	training_sentences = tagged_sentences[0:len(tagged_sentences)*4/5]
	validation_sentences = tagged_sentences[len(tagged_sentences)*8/10+1:len(tagged_sentences)*9/10]
	testing_sentences = tagged_sentences[len(tagged_sentences)*9/10+1:]
	print "Training: %d" % len(training_sentences)
	print "Validation: %d" % len(validation_sentences)
	print "Testing: %d" % len(testing_sentences)

	print testing_sentences
	
	training_stream, validation_stream = map(merge_stream, (training_sentences, validation_sentences))
	stop = time()
	print "Streaming: %f" % (stop-start)

	print "Training"
	start = time()
	pos_tagger = HiddenMarkovModel()
	pos_tagger.train(training_stream[1:-2])
	stop = time()
	print "Training: %f" % (stop-start)

	print "Testing"
	start = time()

	for correct_labels, emissions in testing_sentences:
		guessed_labels = pos_tagger.label(emissions, debug=True)
		num_correct = 0
		for correct, guessed in izip(correct_labels, guessed_labels):
			if correct == START_LABEL or correct == STOP_LABEL: continue
			if correct == guessed: num_correct += 1

		if correct_labels != guessed_labels:
			guessed_score = pos_tagger.score(zip(guessed_labels, emissions))
			correct_score = pos_tagger.score(zip(correct_labels, emissions))

			print "Guessed: %f, Correct: %f" % (guessed_score, correct_score)

			debug_label = lambda: pos_tagger.label([word for _, word in testing_stream[1:-2]], debug=True, start_at=20)
			assert guessed_score >= correct_score, "Decoder sub-optimality (%f for guess, %f for correct), %s" % (guessed_score, correct_score, debug_label())

	stop = time()
	print "Testing: %f" % (stop-start)

	print "%d correct (%.3f%% of %d)" % (num_correct, 100.0 * float(num_correct) / float(len(correct_labels)), len(correct_labels))

def test_problem(args):
	defaults = {START_LABEL : float("-inf"), STOP_LABEL : float("-inf")}

	def uniform_transitions(model):
		for start in ('A', 'B'):
			model.transition[start].update(defaults)
			model.reverse_transition[start].update(defaults)
			for finish in ('A', 'B', STOP_LABEL):
				model.transition[start][finish] = log(1.0 / 3.0)
				model.reverse_transition[finish][start] = log(1.0 / 3.0)
			model.transition[START_LABEL][start] = log(0.5)
			model.reverse_transition[start][START_LABEL] = log(0.5)

	def self_biased_transitions(model):
		for start in ('A', 'B'):
			model.transition[start].update(defaults)
			model.reverse_transition[start].update(defaults)
			for finish in ('A', 'B', STOP_LABEL):
				if start == finish:
					model.transition[start][finish] = log(1.0 / 2.0)
					model.reverse_transition[finish][start] = log(1.0 / 2.0)
				else:
					model.transition[start][finish] = log(1.0 / 4.0)
					model.reverse_transition[finish][start] = log(1.0 / 4.0)
			model.transition[START_LABEL][start] = log(0.5)
			model.reverse_transition[start][START_LABEL] = log(0.5)

	def identity_emissions(model):
		for label in model.labels:
			for emission in model.labels:
				if label == emission:
					model.emission[label][emission] = log(1.0)
					model.label_emissions[emission][label] = log(1.0)
				else:
					model.emission[label][emission] = float("-inf")
					model.label_emissions[emission][label] = float("-inf")

	def self_biased_emissions(model):
		for label in model.labels:
			for emission in model.labels:
				if label == emission:
					model.emission[label][emission] = log(2.0 / 3.0)
					model.label_emissions[emission][label] = log(2.0 / 3.0)
				else:
					model.emission[label][emission] = log(1.0 / (3.0 * float(len(model.labels)-1)))
					model.label_emissions[emission][label] = log(1.0 / (3.0 * float(len(model.labels)-1)))

	def test_label(model, emissions, score, labels=None, debug=False):
		if not labels: labels = emissions
		guessed_labels = model.label(emissions, debug=debug)
		assert sum(label == emission for label, emission in zip(guessed_labels, labels)) == len(emissions)
		guessed_score = model.score(zip(guessed_labels, emissions), debug=debug)
		assert abs(guessed_score - score) < 0.0001, score

	print "Testing emission == state w/ uniform transitions chain: ",

	model = HiddenMarkovModel()
	model.labels = ('A', 'B', START_LABEL, STOP_LABEL)

	uniform_transitions(model)
	identity_emissions(model)

	tests = [['A', 'A', 'A', 'A'], ['B', 'B', 'B', 'B'], ['A', 'A', 'B', 'B'], ['B', 'A', 'B', 'B']]

	for test in tests:
		test_label(model, test, log(1.0 / 2.0) + log(1.0 / 3.0) * 4)

	print "ok"

	print "Testing emissions == labels with non-uniform transitions chain: ",

	model = HiddenMarkovModel()
	model.labels = ('A', 'B', START_LABEL, STOP_LABEL)

	self_biased_transitions(model)
	identity_emissions(model)

	scores = [log(0.5) * 4 + log(0.25), log(0.5) * 4 + log(0.25), log(0.5)*3 + log(0.25)*2, log(0.5)*2 + log(0.25)*3]
	scored_tests = zip(tests, scores)

	for test, score in scored_tests:
		test_label(model, test, score)

	print "ok"

	print "Testing uniform transitions with self-biased emissions: ",

	model = HiddenMarkovModel()
	model.labels = ('A', 'B', START_LABEL, STOP_LABEL)

	uniform_transitions(model)
	self_biased_emissions(model)

	scores = [log(0.5) + log(1.0 / 3.0) * 4.0 + 4.0 * log(2.0 / 3.0) for i in xrange(4)]
	scored_tests = zip(tests, scores)

	for test, score in scored_tests:
		test_label(model, test, score)

	print "ok"

	print "Testing self-biased transitions with self-biased emissions: ",

	model = HiddenMarkovModel()
	model.labels = ('A', 'B', START_LABEL, STOP_LABEL)

	self_biased_transitions(model)
	self_biased_emissions(model)

	scores = [log(0.5) * 4 + log(0.25), log(0.5) * 4 + log(0.25), log(0.5)*3 + log(0.25)*2, log(0.5)*2 + log(0.25)*3]
	scores = [4.0 * log(2.0 / 3.0) + score for score in scores]
	scored_tests = zip(tests, scores)

	for test, score in scored_tests:
		test_label(model, test, score)

	print "ok"

	print "Testing UNK emission with emission == label and self-biased transitions: ",

	model = HiddenMarkovModel()
	model.labels = ('A', 'B', START_LABEL, STOP_LABEL)

	identity_emissions(model)
	self_biased_transitions(model)

	emissions = ['A', 'C', 'A', 'B', 'B']
	labels = ['A', 'A', 'A', 'B', 'B']
	score = log(0.5) * 2 + log(0.25) + log(0.5) + log(0.25) + log(0.5) + log(0.25)

	test_label(model, emissions, score, labels=labels)

	emissions = ['A', 'C', 'C', 'B', 'B']
	labels = [['A', 'A', 'A', 'B', 'B'], ['A', 'A', 'B', 'B', 'B'], ['A', 'B', 'B', 'B', 'B']]

	score = None
	for label in labels:
		new_score = model.score(zip(label, emissions))
		if score: assert score == new_score, "score(%s) (%f) bad" % (label, new_score)
		score = new_score

	emissions = ['A', 'C', 'C', 'B', 'B']
	labels = [['A', 'A', 'A', 'B', 'B'], ['A', 'A', 'B', 'B', 'B'], ['A', 'B', 'B', 'B', 'B']]

	score = None
	for label in labels:
		new_score = model.score(zip(label, emissions))
		if score: assert score == new_score, "score(%s) (%f) bad" % (label, new_score)
		score = new_score

	print "ok"
	
def main(args):
	if args[0] == 'toy': toy_problem(args[1:])
	elif args[0] == 'debug': debug_problem(args[1:])
	elif args[0] == 'pos': pos_problem(args[1:])
	elif args[0] == 'test': test_problem(args[1:])

if __name__ == "__main__":
	main(sys.argv[1:])
