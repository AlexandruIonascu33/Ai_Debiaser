// static/js/experiment_en.js

document.addEventListener('DOMContentLoaded', async () => {
    const hasActiveParticipantSession = document.body.dataset.hasActiveParticipantSession === 'true';
    
    // ==========================================
    // 1. EXPERIMENT STATE (STATE MANAGEMENT)
    // ==========================================
    
    const STATE = {
        participantId: null, // Will be populated by backend
        stimuliList: [],
        currentTrial: 0,
        trialStartTime: 0,
        phaseStartTime: 0,
        totalTrials: 4,
        evaluationPhase: 'pre', // 'pre', 'post', 'recall'
        preEvaluationData: null,
        postEvaluationData: null,
        initialSubmissionId: null,
        finalSubmissionId: null,
        aiChatHistory: [],
        hasSentReflectionMessage: false,
        isChatActive: false,
        hasAdjustedBonusSlider: false,
        experimentalCondition: null
    };

    // ==========================================
    // 2. STIMULI AND INSTRUMENTS DEFINITION
    // ==========================================

    const STIMULI_POOL = [
        { id: 'it_2', domain: 'IT', role: 'Full-stack Developer', name: 'Brian Lewis', photo: 'it_2.jpg', age: 29, performance_score: 97, performance_label: 'Top Performer', performance_rank: 'Ranked among the highest-performing 2% of employees in this role.', performance_evidence: 'Based on standardized technical performance assessments and quarterly role-specific outcomes, he scored in the top-performing range for this role. Over the past four quarters, he delivered all assigned releases on schedule and resolved 24% more production issues than the team average.' },
        { id: 'it_3', domain: 'IT', role: 'Software Developer', name: 'Daniel Moore', photo: 'it_3.jpg', age: 30, performance_score: 26, performance_label: 'Low Performer', performance_rank: 'Ranked among the lowest-performing 20% of employees in this role.', performance_evidence: 'Based on standardized technical performance assessments and quarterly role-specific outcomes, he scored in the lower-performing range for this role. Over the past four quarters, he missed a substantial share of agreed delivery targets and required additional support on several release-critical tasks.' },
        { id: 'sales_2', domain: 'Sales', role: 'Retail Sales Advisor', name: 'Michael Anderson', photo: 'sales_2.jpg', age: 31, performance_score: 93, performance_label: 'Top Performer', performance_rank: 'Ranked among the highest-performing 2% of employees in this role.', performance_evidence: 'Based on standardized sales-performance assessments and quarterly role-specific outcomes, he scored in the top-performing range for this role. Over the past four quarters, he exceeded quarterly sales targets by more than 20% and maintained one of the highest customer-retention rates in the division.' },
        { id: 'sales_5', domain: 'Sales', role: 'Telemarketing Agent', name: 'Ryan Thomas', photo: 'sales_5.jpg', age: 30, performance_score: 31, performance_label: 'Low Performer', performance_rank: 'Ranked among the lowest-performing 20% of employees in this role.', performance_evidence: 'Based on standardized sales-performance assessments and quarterly role-specific outcomes, he scored in the lower-performing range for this role. Over the past four quarters, he fell short of sales targets and recorded conversion rates below the division average.' }
    ];

    const PERFORMANCE_RECALL_OPTIONS = [
        { value: 'low_performance', label: 'Low performance' },
        { value: 'average_performance', label: 'Average performance' },
        { value: 'high_performance', label: 'High performance' },
        { value: 'do_not_remember', label: 'I do not remember' }
    ];

    const QUESTIONS = {
        A_LEADERSHIP: [
            "This person has the potential to become an effective leader.",
            "This person has the capacity to learn leadership skills.",
            "This person can advance into a leadership position.",
            "This person can become a role model for their colleagues."
        ],
        B_PROMOTABILITY: [
            "I believe this employee will have a successful career.",
            "If I had to choose a successor for my position, this person would be a suitable candidate.",
            "I believe this employee has high overall potential."
        ]
    };

    const AI_USEFULNESS_ITEMS = [
        'Using the AI assistant helped me complete the evaluation more effectively.',
        'Using the AI assistant made it easier to evaluate the candidate.',
        'Overall, I found the AI assistant useful for this task.'
    ];
    const MIN_JUSTIFICATION_LENGTH = 50;
    const MIN_AI_RESPONSE_LENGTH = 30;
    const AI_ASSISTED_CONDITION = 'ai_assisted';

    const ATTENTION_CHECK_PLACEMENTS = [
        { pre: { block: 'leadership', index: 1 }, post: { block: 'promotability', index: 0 } },
        { pre: { block: 'promotability', index: 1 }, post: { block: 'leadership', index: 2 } },
        { pre: { block: 'leadership', index: 0 }, post: { block: 'promotability', index: 2 } },
        { pre: { block: 'promotability', index: 0 }, post: { block: 'leadership', index: 1 } }
    ];

    // ==========================================
    // 3. IMAGE PRELOADING (BROWSER CACHE)
    // ==========================================

    function preloadImages() {
        STIMULI_POOL.forEach(stimulus => {
            const img = new Image();
            img.src = `/static/img/${stimulus.photo}`;
        });
    }

    // ==========================================
    // 4. SESSION INITIALIZATION (API COMMUNICATION)
    // ==========================================

    async function initializeSession() {
        try {
            // Preload all images to cache before first trial
            preloadImages();

            const randomizedProfiles = [...STIMULI_POOL];
            for (let i = randomizedProfiles.length - 1; i > 0; i--) {
                const j = Math.floor(Math.random() * (i + 1));
                [randomizedProfiles[i], randomizedProfiles[j]] = [randomizedProfiles[j], randomizedProfiles[i]];
            }
            
            const response = await fetch('/api/init_session', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    consent_accepted: true,
                    profile_order: randomizedProfiles.map(profile => profile.id)
                })
            });
            if (!response.ok) throw new Error('Error initializing the database.');
            
            const data = await response.json();
            STATE.participantId = data.participant_id;
            STATE.experimentalCondition = data.experimental_condition;
            STATE.stimuliList = data.profile_order.map(profileId =>
                STIMULI_POOL.find(profile => profile.id === profileId)
            ).filter(Boolean);
            STATE.totalTrials = STATE.stimuliList.length;
            STATE.currentTrial = data.current_trial_index;

            configureConditionUI();
            if (data.study_stage === 'final_recall') {
                showFinalRecallModal();
                return true;
            }
            if (data.study_stage === 'final_questionnaire') {
                showFinalQuestionnaireModal();
                return true;
            }
            if (data.study_stage === 'post_evaluation') {
                initUI();
                loadTrial(data.initial_evaluation);
                return true;
            }
            if (data.study_stage !== 'evaluation' || STATE.currentTrial >= STATE.totalTrials) {
                throw new Error('This study session has already been completed.');
            }
            
            initUI();
            loadTrial();
            return true;
            
        } catch (error) {
            console.error("Critical System Error:", error);
            alert("The system could not initialize the session. Please refresh the page.");
            return false;
        }
    }

    // ==========================================
    // 5. USER INTERFACE GENERATION
    // ==========================================

    function createLikertScale(containerId, inputName) {
        const container = document.getElementById(containerId);
        if (!container) return;
        
        let html = '<div class="likert-container w-100">';
        html += '<span class="x-small">Strongly<br>Disagree</span>';
        
        for (let i = 1; i <= 7; i++) {
            html += `
                <div class="likert-item">
                    <input type="radio" name="${inputName}" value="${i}" id="${inputName}_${i}">
                    <label for="${inputName}_${i}">${i}</label>
                </div>
            `;
        }
        
        html += '<span class="x-small text-end">Strongly<br>Agree</span>';
        html += '</div>';
        container.innerHTML = html;
    }

    function initUI() {
        renderEvaluationItems('pre');
    }

    function isAiAssistedCondition() {
        return STATE.experimentalCondition === AI_ASSISTED_CONDITION;
    }

    function configureConditionUI() {
        const isAiAssisted = isAiAssistedCondition();
        const aiChatLaunch = document.getElementById('aiChatLaunch');
        const aiUsefulnessSection = document.getElementById('aiUsefulnessSection');
        const justificationInstruction = document.getElementById('justificationInstruction');
        const finalInstruction = document.getElementById('finalEvaluationInstruction');

        aiChatLaunch.classList.toggle('d-none', !isAiAssisted);
        aiUsefulnessSection.classList.toggle('d-none', !isAiAssisted);
        justificationInstruction.innerText = isAiAssisted
            ? 'Please explain the reasoning behind your ratings in a few words. You will then discuss your reasoning with the AI assistant before completing your final evaluation.'
            : 'Please explain the reasoning behind your ratings in a few words. After your justification, you may confirm or revise your final evaluation.';

        if (!isAiAssisted) {
            finalInstruction.innerText = 'After completing your justification, please confirm or, if appropriate, revise your final evaluations for this candidate.';
        }
        finalInstruction.classList.add('d-none');
    }

    function configurePerformanceTransitionModal() {
        const isAiAssisted = isAiAssistedCondition();
        document.getElementById('performanceTransitionIntro').innerText = isAiAssisted
            ? 'The candidate\'s prior performance information is now available in the profile panel. Review it, explain your initial evaluation, and discuss your reasoning with the AI assistant before your final evaluation.'
            : 'The candidate\'s prior performance information is now available in the profile panel. Review it, provide your justification, and then complete your final evaluation.';
        const steps = [
            {
                title: 'Review the performance score and details',
                detail: 'Read the information shown below the candidate\'s profile.'
            },
            {
                title: 'Explain your initial evaluation',
                detail: 'Write a short justification based on the available evidence.'
            },
        ];

        if (isAiAssisted) {
            steps.push({
                title: 'Discuss your reasoning with the AI assistant',
                detail: 'Send a substantive response to the assistant about your evaluation.'
            });
        }

        steps.push({
            title: 'Review your final evaluation',
            detail: 'Confirm or, if appropriate, revise all ratings and the bonus allocation.'
        });

        document.getElementById('performanceTransitionSteps').innerHTML = steps.map((step, index) => `
            <li><span>${index + 1}</span><div><strong>${step.title}</strong><small>${step.detail}</small></div></li>
        `).join('');
    }

    function renderEvaluationItems(phase) {
        const containerA = document.getElementById('blockA_container');
        const containerB = document.getElementById('blockB_container');
        const placement = ATTENTION_CHECK_PLACEMENTS[STATE.currentTrial % ATTENTION_CHECK_PLACEMENTS.length][phase];
        const expectedResponse = phase === 'pre' ? 2 : 6;
        containerA.innerHTML = '';
        containerB.innerHTML = '';

        QUESTIONS.A_LEADERSHIP.forEach((q, index) => {
            const id = `lead_${index + 1}`;
            containerA.innerHTML += `<label class="small d-block mt-2 fw-semibold text-dark">${index + 1}. ${q}</label>
                                     <div id="likert_${id}"></div>`;
            createLikertScale(`likert_${id}`, id);

            if (placement.block === 'leadership' && placement.index === index) {
                addAttentionCheck(containerA, expectedResponse);
            }
        });

        QUESTIONS.B_PROMOTABILITY.forEach((q, index) => {
            const id = `prom_${index + 1}`;
            containerB.innerHTML += `<label class="small d-block mt-2 fw-semibold text-dark">${index + 1}. ${q}</label>
                                     <div id="likert_${id}"></div>`;
            createLikertScale(`likert_${id}`, id);

            if (placement.block === 'promotability' && placement.index === index) {
                addAttentionCheck(containerB, expectedResponse);
            }
        });
    }

    function addAttentionCheck(container, expectedResponse) {
        container.insertAdjacentHTML('beforeend', `
            <div class="attention-check-item my-3">
                <label class="small d-block mt-2 fw-semibold text-dark">Please select response ${expectedResponse} for this statement.</label>
                <div id="attentionCheckContainer"></div>
            </div>`);
        createLikertScale('attentionCheckContainer', 'attention_check');
    }

    function renderAiUsefulnessItems() {
        const container = document.getElementById('aiUsefulnessContainer');
        if (!container) return;

        container.innerHTML = AI_USEFULNESS_ITEMS.map((question, index) => `
            <div class="mb-3">
                <label class="small d-block fw-semibold text-dark">${index + 1}. ${question}</label>
                <div id="ai_usefulness_${index + 1}"></div>
            </div>
        `).join('');

        AI_USEFULNESS_ITEMS.forEach((_, index) => {
            createLikertScale(`ai_usefulness_${index + 1}`, `ai_usefulness_${index + 1}`);
        });
    }

    // ==========================================
    // 6. EXECUTION LOGIC (TRIAL PIPELINE)
    // ==========================================

    function loadTrial(savedInitialEvaluation = null) {
        const currentData = STATE.stimuliList[STATE.currentTrial];
        
        // Update Progress
        document.getElementById('progressContainer').classList.remove('d-none');
        document.getElementById('progressText').innerText = `Profile ${STATE.currentTrial + 1} / ${STATE.totalTrials}`;
        document.getElementById('progressBar').style.width = `${((STATE.currentTrial + 1) / STATE.totalTrials) * 100}%`;

        // Populate Stimulus
        document.getElementById('stimulusName').innerText = currentData.name;
        document.getElementById('stimulusRole').innerText = currentData.role;
        document.getElementById('stimulusDomain').innerText = currentData.domain;
        document.getElementById('stimulusAge').innerText = currentData.age + ' years';
        
        // Populate Prior Performance Evidence
        const performanceScore = currentData.performance_score;
        const performanceTextEl = document.getElementById('performanceTextValue');
        const performanceBarEl = document.getElementById('performanceBarValue');
        const performanceDomainEl = document.getElementById('performanceDomainText');
        const performanceEvidenceEl = document.getElementById('performanceEvidenceText');
        const performanceLabelEl = document.getElementById('performanceLabel');
        const performanceRankingEl = document.getElementById('performanceRankingText');

        if (performanceTextEl && performanceBarEl && performanceDomainEl && performanceEvidenceEl && performanceLabelEl && performanceRankingEl) {
            performanceTextEl.innerText = `${performanceScore} / 100`;
            performanceBarEl.style.width = `${performanceScore}%`;
            performanceBarEl.setAttribute('aria-valuenow', performanceScore);
            performanceDomainEl.innerText = `Prior ${currentData.domain} Performance`;
            performanceLabelEl.innerText = currentData.performance_label;
            performanceLabelEl.classList.toggle('is-low-performer', currentData.performance_label === 'Low Performer');
            performanceRankingEl.innerText = currentData.performance_rank;
            performanceEvidenceEl.innerText = currentData.performance_evidence;
        }

        // Image (Placeholder fallback)
        const photoEl = document.getElementById('stimulusPhoto');
        photoEl.src = `/static/img/${currentData.photo}`;
        photoEl.onerror = function() {
            this.src = `https://via.placeholder.com/220x270.png?text=PHOTO+${currentData.domain}`;
        };

        // Hide dynamic sections
        document.getElementById('performanceSection').style.display = 'none';
        document.getElementById('justificationSection').style.display = 'none';
        document.getElementById('demand_awareness').value = '';
        document.getElementById('rating_change_reason').value = '';
        const aiUsefulnessContainer = document.getElementById('aiUsefulnessContainer');
        if (aiUsefulnessContainer) aiUsefulnessContainer.innerHTML = '';

        // Reset button
        const btn = document.getElementById('btnNext');
        btn.classList.remove('d-none');
        btn.innerText = 'SUBMIT FIRST EVALUATION';
        if (btn.classList.contains('btn-success')) {
            btn.classList.replace('btn-success', 'btn-primary');
        }
        document.getElementById('postEvaluationActions').classList.add('d-none');

        // Reset state for new trial
        STATE.evaluationPhase = 'pre';
        STATE.preEvaluationData = null;
        STATE.postEvaluationData = null;
        STATE.initialSubmissionId = savedInitialEvaluation ? null : createSubmissionId();
        STATE.finalSubmissionId = null;
        STATE.aiChatHistory = [];
        STATE.hasSentReflectionMessage = false;
        STATE.isChatActive = false;
        document.getElementById('justification_text').value = '';
        closeChatPanel();
        configureConditionUI();
        renderEvaluationItems('pre');
        clearInstruments();

        // Reset timer
        STATE.trialStartTime = performance.now();
        STATE.phaseStartTime = STATE.trialStartTime;
        window.scrollTo(0, 0);

        if (savedInitialEvaluation) {
            beginPostEvaluation(savedInitialEvaluation);
        }
    }

    function createSubmissionId() {
        if (window.crypto?.randomUUID) {
            return window.crypto.randomUUID();
        }
        return `${Date.now()}-${Math.random().toString(36).slice(2, 18)}`;
    }

    function getRadioValue(name) {
        const element = document.querySelector(`input[name="${name}"]:checked`);
        return element ? parseInt(element.value) : null;
    }

    function collectEvaluationData() {
        const data = {
            lead_1: getRadioValue('lead_1'),
            lead_2: getRadioValue('lead_2'),
            lead_3: getRadioValue('lead_3'),
            lead_4: getRadioValue('lead_4'),
            prom_1: getRadioValue('prom_1'),
            prom_2: getRadioValue('prom_2'),
            prom_3: getRadioValue('prom_3'),
            bonus_allocation: parseInt(document.getElementById('bonus_slider').value),
            attention_check: getRadioValue('attention_check'),
        };

        if (!STATE.hasAdjustedBonusSlider) {
            alert('Please move the bonus slider at least once before continuing. You may return it to $0.');
            document.getElementById('bonus_slider').focus();
            return null;
        }
    
        const requiredLikertFields = [
            'lead_1', 'lead_2', 'lead_3', 'lead_4',
            'prom_1', 'prom_2', 'prom_3'
        ];
    
        const hasMissingData = requiredLikertFields.some(field => data[field] === null) || data.attention_check === null;
        if (hasMissingData) {
            alert('Please answer all rating and instruction-check questions before continuing.');
            return null;
        }
        return data;
    }

    function clearInstruments() {
        document.querySelectorAll('input[type="radio"]').forEach(radio => radio.checked = false);
        document.getElementById('bonus_slider').value = 0;
        document.getElementById('bonus_value').innerText = '$0';
        STATE.hasAdjustedBonusSlider = false;
        updateBonusSliderState();
    }

    function updateBonusSliderState() {
        const button = document.getElementById('btnNext');
        const hint = document.getElementById('bonusInteractionHint');
        const isReady = STATE.hasAdjustedBonusSlider;

        button.disabled = STATE.evaluationPhase === 'pre' && !isReady;
        hint.classList.toggle('is-complete', isReady);
        hint.innerText = isReady
            ? 'Bonus amount recorded. You may continue after completing all required ratings.'
            : 'Move the slider before submitting. You may return it to $0.';
    }

    function beginPostEvaluation(initialEvaluationData) {
        STATE.preEvaluationData = initialEvaluationData;
        STATE.finalSubmissionId = createSubmissionId();
        document.getElementById('performanceSection').style.display = 'block';
        document.getElementById('justificationSection').style.display = 'block';
        STATE.evaluationPhase = 'post';
        clearInstruments();
        STATE.phaseStartTime = performance.now();
        renderEvaluationItems('post');
        document.getElementById('btnNext').classList.add('d-none');
        document.getElementById('postEvaluationActions').classList.add('d-none');
        const submitButton = document.getElementById('btnSubmitFinalEvaluation');
        submitButton.disabled = false;
        submitButton.innerText = 'SUBMIT EVALUATION AND CONTINUE';
        showPerformanceTransitionModal();
    }

    function updatePostEvaluationActions() {
        if (STATE.evaluationPhase !== 'post') return;

        const justificationText = document.getElementById('justification_text').value.trim();
        const isReadyForReview = justificationText.length >= MIN_JUSTIFICATION_LENGTH
            && (!isAiAssistedCondition() || STATE.hasSentReflectionMessage);
        document.getElementById('postEvaluationActions').classList.toggle('d-none', !isReadyForReview);

        if (!isAiAssistedCondition()) {
            document.getElementById('finalEvaluationInstruction').classList.toggle('d-none', justificationText.length < MIN_JUSTIFICATION_LENGTH);
        }
    }

    function returnToEvaluation() {
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    async function saveInitialEvaluation(evaluationData) {
        const btn = document.getElementById('btnNext');
        btn.disabled = true;
        btn.innerText = 'SAVING...';

        try {
            const response = await fetch('/api/save_initial_evaluation', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    participant_id: STATE.participantId,
                    profile_id: STATE.stimuliList[STATE.currentTrial].id,
                    submission_id: STATE.initialSubmissionId,
                    reaction_time_ms: Math.round(performance.now() - STATE.phaseStartTime),
                    ...evaluationData,
                })
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.message || 'Error saving the initial evaluation.');

            beginPostEvaluation(data.initial_evaluation);
        } catch (error) {
            console.error(error);
            alert(error.message || 'A server connection error occurred. Please try again.');
            btn.innerText = 'SUBMIT FIRST EVALUATION';
            updateBonusSliderState();
        }
    }

    async function handleNext() {
        // --- PHASE 1: PRE-PERFORMANCE EVALUATION ---
        if (STATE.evaluationPhase === 'pre') {
            const evaluationData = collectEvaluationData();
            if (!evaluationData) return; // Validation failed
            await saveInitialEvaluation(evaluationData);
            return;
        }

        // --- PHASE 2: POST-PERFORMANCE EVALUATION & JUSTIFICATION ---
        if (STATE.evaluationPhase === 'post') {
            const evaluationData = collectEvaluationData();
            if (!evaluationData) return; // Validation failed
    
            const justificationText = document.getElementById('justification_text').value.trim();
            if (justificationText.length < MIN_JUSTIFICATION_LENGTH) {
                alert('Please explain your reasoning in a few words before continuing.');
                return;
            }
            if (isAiAssistedCondition() && !STATE.hasSentReflectionMessage) {
                alert('Please respond to the AI assistant at least once before continuing.');
                openChatPanel();
                return;
            }

            STATE.postEvaluationData = evaluationData;
            await saveAllData();
        }
    }

    // ==========================================
    // 7. AI CHAT LOGIC
    // ==========================================

    async function openChatPanel() {
        if (!isAiAssistedCondition()) {
            return;
        }

        const justification = document.getElementById('justification_text').value.trim();
        if (justification.length < MIN_JUSTIFICATION_LENGTH) {
            alert('Please explain your reasoning in a few words before starting the reflection.');
            updatePostEvaluationActions();
            return;
        }

        document.getElementById('aiChatPanel').classList.remove('d-none');
        document.getElementById('btnRestoreChat').classList.add('d-none');
        if (STATE.aiChatHistory.length) {
            displayChatMessages();
            document.getElementById('chatInput').focus();
            return;
        }
        document.getElementById('chatMessages').innerHTML = '<p class="text-muted small">The assistant is reviewing your justification...</p>';

        try {
            const response = await fetch('/api/ai_chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    participant_id: STATE.participantId,
                    profile_id: STATE.stimuliList[STATE.currentTrial].id,
                    justification,
                    evaluation_context: getAiEvaluationContext(),
                    history: []
                })
            });
            const data = await response.json();

            if (!response.ok) throw new Error(data.message || 'Error communicating with the AI.');

            STATE.aiChatHistory.push({ role: 'user', content: justification });
            STATE.aiChatHistory.push({ role: 'assistant', content: data.response });

            displayChatMessages();
        } catch (error) {
            console.error(error);
            document.getElementById('chatMessages').innerHTML = `<p class="text-danger small">${error.message}</p>`;
        }
    }

    function displayChatMessages() {
        const container = document.getElementById('chatMessages');
        container.innerHTML = '';
        STATE.aiChatHistory.forEach(msg => {
            const div = document.createElement('div');
            div.className = `chat-bubble ${msg.role === 'user' ? 'user' : 'ai'}`;
            div.innerText = msg.role === 'user' ? `Justification: ${msg.content}` : msg.content;
            container.appendChild(div);
        });
        container.scrollTop = container.scrollHeight;
    }

    async function sendChatMessage() {
        const input = document.getElementById('chatInput');
        const message = input.value.trim();
        if (message.length < MIN_AI_RESPONSE_LENGTH) {
            alert('Please respond to the AI assistant in a few words.');
            input.focus();
            return;
        }

        STATE.aiChatHistory.push({ role: 'user', content: message });
        displayChatMessages();
        input.value = '';
        input.disabled = true;

        try {
            const response = await fetch('/api/ai_chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    participant_id: STATE.participantId,
                    profile_id: STATE.stimuliList[STATE.currentTrial].id,
                    evaluation_context: getAiEvaluationContext(),
                    history: STATE.aiChatHistory
                })
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.message || 'Error communicating with the AI.');

            STATE.aiChatHistory.push({ role: 'assistant', content: data.response });
            STATE.hasSentReflectionMessage = true;
            displayChatMessages();
            const finalInstruction = document.getElementById('finalEvaluationInstruction');
            finalInstruction.innerHTML = '<strong>Thank you for reflecting.</strong> Taking the discussion into account, please now <strong>confirm or, if appropriate, revise your final evaluations</strong> for this candidate.';
            finalInstruction.classList.remove('d-none');
            updatePostEvaluationActions();
            finalInstruction.scrollIntoView({ behavior: 'smooth', block: 'center' });
        } catch (error) {
            console.error(error);
        } finally {
            input.disabled = false;
            input.focus();
        }
    }

    function getAiEvaluationContext() {
        const profile = STATE.stimuliList[STATE.currentTrial];
        return {
            profile_id: profile.id,
            candidate_profile: {
                name: profile.name,
                role: profile.role,
                domain: profile.domain,
                age: profile.age,
                work_experience: '5 years',
                performance_score: profile.performance_score,
                performance_evidence: profile.performance_evidence
            },
            leadership_items: QUESTIONS.A_LEADERSHIP.map((question, index) => ({
                question,
                response: STATE.preEvaluationData[`lead_${index + 1}`]
            })),
            promotability_items: QUESTIONS.B_PROMOTABILITY.map((question, index) => ({
                question,
                response: STATE.preEvaluationData[`prom_${index + 1}`]
            })),
            bonus_allocation: STATE.preEvaluationData.bonus_allocation,
            participant_justification: document.getElementById('justification_text').value.trim()
        };
    }

    async function saveAllData() {
        const submitButton = document.getElementById('btnSubmitFinalEvaluation');
        submitButton.disabled = true;
        submitButton.innerText = 'SAVING...';

        const payload = {
            participant_id: STATE.participantId,
            profile_id: STATE.stimuliList[STATE.currentTrial].id,
            submission_id: STATE.finalSubmissionId,
            post_reaction_time_ms: Math.round(performance.now() - STATE.phaseStartTime),
            justification_text: document.getElementById('justification_text').value.trim(),
            ai_conversation: isAiAssistedCondition() && STATE.aiChatHistory.length > 0 ? JSON.stringify(STATE.aiChatHistory) : null,
        };

        for (const key in STATE.postEvaluationData) {
            payload[`${key}_post`] = STATE.postEvaluationData[key];
        }

        try {
            const saveResponse = await fetch('/api/save_trial', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            const saveData = await saveResponse.json();
            if (!saveResponse.ok) throw new Error(saveData.message || 'Error saving trial.');
            closeChatPanel();

            // Check if we reached the last stimulus
            if (STATE.currentTrial === STATE.totalTrials - 1) {
                showFinalRecallModal();
                return;
            }

            // Move to next profile in randomized matrix
            STATE.currentTrial++;
            loadTrial();
            clearInstruments();

        } catch (error) {
            console.error(error);
            alert(error.message || 'A server connection error occurred. Please try again.');
            submitButton.disabled = false;
            submitButton.innerText = 'SUBMIT EVALUATION AND CONTINUE';
        }
    }

    function showFinalRecallModal() {
        document.getElementById('performanceSection').style.display = 'none';
        const container = document.getElementById('finalRecallContainer');
        container.innerHTML = STATE.stimuliList.map((stimulus, index) => `
            <div class="d-flex align-items-center gap-3 p-3 mb-3 border rounded bg-light">
                <img src="/static/img/${stimulus.photo}" alt="${stimulus.name}" class="img-thumbnail" style="width: 72px; height: 90px; object-fit: cover;">
                <div class="flex-grow-1">
                    <label class="form-label fw-semibold" for="recall_${stimulus.id}">${index + 1}. ${stimulus.name}</label>
                    <input type="number" class="form-control" id="recall_${stimulus.id}" min="0" max="100" step="1" placeholder="Performance score (0-100)">
                    <label class="form-label small fw-semibold mt-2 mb-1" for="recall_category_${stimulus.id}">Overall performance category</label>
                    <select class="form-select" id="recall_category_${stimulus.id}">
                        <option value="">Select a category</option>
                        ${PERFORMANCE_RECALL_OPTIONS.map(option => `<option value="${option.value}">${option.label}</option>`).join('')}
                    </select>
                </div>
            </div>
        `).join('');

        const modal = new bootstrap.Modal(document.getElementById('finalRecallModal'));
        modal.show();
    }

    function showPerformanceTransitionModal() {
        configurePerformanceTransitionModal();
        const modalElement = document.getElementById('performanceTransitionModal');
        modalElement.addEventListener('hidden.bs.modal', () => {
            document.getElementById('performanceSection').scrollIntoView({ behavior: 'smooth', block: 'start' });
        }, { once: true });
        bootstrap.Modal.getOrCreateInstance(modalElement, {
            backdrop: 'static',
            keyboard: false
        }).show();
    }

    function showFinalQuestionnaireModal() {
        if (isAiAssistedCondition()) {
            renderAiUsefulnessItems();
        }
        const modal = new bootstrap.Modal(document.getElementById('finalQuestionnaireModal'));
        modal.show();
    }

    function closeChatPanel() {
        document.getElementById('aiChatPanel').classList.add('d-none');
        document.getElementById('btnRestoreChat').classList.add('d-none');
    }

    function minimizeChatPanel() {
        document.getElementById('aiChatPanel').classList.add('d-none');
        document.getElementById('btnRestoreChat').classList.remove('d-none');
    }

    function restoreChatPanel() {
        document.getElementById('aiChatPanel').classList.remove('d-none');
        document.getElementById('btnRestoreChat').classList.add('d-none');
        document.getElementById('chatInput').focus();
    }

    async function submitFinalRecall() {
        const recalledPerformanceScores = {};
        const recalledPerformanceCategories = {};
        for (const stimulus of STATE.stimuliList) {
            const input = document.getElementById(`recall_${stimulus.id}`);
            const score = Number(input.value);
            if (!Number.isInteger(score) || score < 0 || score > 100) {
                alert('Please enter a whole-number performance score between 0 and 100 for every candidate.');
                input.focus();
                return;
            }
            recalledPerformanceScores[stimulus.id] = score;

            const categoryInput = document.getElementById(`recall_category_${stimulus.id}`);
            if (!PERFORMANCE_RECALL_OPTIONS.some(option => option.value === categoryInput.value)) {
                alert('Please select an overall performance category for every candidate.');
                categoryInput.focus();
                return;
            }
            recalledPerformanceCategories[stimulus.id] = categoryInput.value;
        }

        const submitButton = document.getElementById('btnSubmitFinalRecall');
        submitButton.disabled = true;
        try {
            const recallResponse = await fetch('/api/save_final_recall', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    participant_id: STATE.participantId,
                    recalled_performance_scores: recalledPerformanceScores,
                    recalled_performance_categories: recalledPerformanceCategories
                })
            });
            const recallData = await recallResponse.json();
            if (!recallResponse.ok) {
                throw new Error(recallData.message || 'Error saving final recall responses.');
            }

            const recallModalElement = document.getElementById('finalRecallModal');
            recallModalElement.addEventListener('hidden.bs.modal', showFinalQuestionnaireModal, { once: true });
            bootstrap.Modal.getInstance(recallModalElement).hide();
        } catch (error) {
            console.error(error);
            alert(error.message || 'A server connection error occurred. Please try again.');
            submitButton.disabled = false;
        }
    }

    async function submitFinalQuestionnaire() {
        const demandText = document.getElementById('demand_awareness').value.trim();
        const ratingChangeReason = document.getElementById('rating_change_reason').value.trim();
        const aiUsefulness = {};
        AI_USEFULNESS_ITEMS.forEach((_, index) => {
            aiUsefulness[`ai_usefulness_${index + 1}`] = getRadioValue(`ai_usefulness_${index + 1}`);
        });
        const demographics = {};
        const demographicFields = [
            'demographic_age_range', 'demographic_gender', 'demographic_work_status',
            'demographic_work_field', 'demographic_work_experience'
        ];
        for (const fieldName of demographicFields) {
            const field = document.getElementById(fieldName);
            if (!field.value) {
                alert('Please complete all demographic questions or select Prefer not to say.');
                field.focus();
                return;
            }
            demographics[fieldName] = field.value;
        }
        const nationality = document.getElementById('demographic_nationality').value.trim();
        if (!nationality) {
            alert('Please enter your nationality or type Prefer not to say.');
            document.getElementById('demographic_nationality').focus();
            return;
        }
        demographics.demographic_nationality = nationality;

        if (!ratingChangeReason) {
            alert('Please describe what influenced your evaluations, or state that they did not change.');
            return;
        }
        if (!demandText) {
            alert("Please complete the final question about the study's purpose before submitting.");
            return;
        }
        if (isAiAssistedCondition() && Object.values(aiUsefulness).some(response => response === null)) {
            alert('Please answer all questions about the AI assistant before submitting.');
            return;
        }

        const submitButton = document.getElementById('btnSubmitFinalQuestionnaire');
        submitButton.disabled = true;
        try {
            const finishResponse = await fetch('/api/finish_session', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    participant_id: STATE.participantId,
                    demand_awareness: demandText,
                    rating_change_reason: ratingChangeReason,
                    ...aiUsefulness,
                    ...demographics
                })
            });
            const finishData = await finishResponse.json();
            if (!finishResponse.ok) {
                throw new Error(finishData.message || 'Error completing the study.');
            }

            showDebrief(finishData.completion_url);
        } catch (error) {
            console.error(error);
            alert(error.message || 'A server connection error occurred. Please try again.');
            submitButton.disabled = false;
        }
    }

    function showDebrief(completionUrl) {
        document.body.innerHTML = `
            <main class="container py-5">
                <section class="debrief-panel mx-auto">
                    <span class="debrief-eyebrow">Study complete</span>
                    <h1 class="h3 fw-bold mt-2">Thank you for taking part</h1>
                    <h2 class="h5 fw-semibold mt-4">About this study</h2>
                    <p>This study examines how people evaluate employees' leadership potential after reviewing a profile and objective performance information. It also examines whether having an opportunity to reflect with an AI assistant changes how people review their evaluations.</p>
                    <p>The candidate profiles and performance information were research materials created for this study. There were no correct ratings, and the study does not evaluate your ability as a rater.</p>
                    <p>Please avoid sharing the detailed study procedures with prospective participants until data collection is complete.</p>
                    <div id="debriefCompletionAction" class="mt-4"></div>
                </section>
            </main>
        `;

        if (completionUrl) {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'btn btn-primary';
            button.innerText = 'RETURN TO PROLIFIC';
            button.addEventListener('click', () => window.location.assign(completionUrl));
            document.getElementById('debriefCompletionAction').appendChild(button);
        }
    }

    // ==========================================
    // 8. EXECUTION TRIGGER
    // ==========================================
    
    document.getElementById('btnNext').addEventListener('click', handleNext);
    document.getElementById('btnSubmitFinalEvaluation').addEventListener('click', handleNext);
    document.getElementById('btnReviewEvaluation').addEventListener('click', returnToEvaluation);
    document.getElementById('btnSendChat').addEventListener('click', sendChatMessage);
    document.getElementById('btnSubmitFinalRecall').addEventListener('click', submitFinalRecall);
    document.getElementById('btnSubmitFinalQuestionnaire').addEventListener('click', submitFinalQuestionnaire);
    document.getElementById('btnOpenChat').addEventListener('click', openChatPanel);
    document.getElementById('btnCloseChat').addEventListener('click', closeChatPanel);
    document.getElementById('btnMinimizeChat').addEventListener('click', minimizeChatPanel);
    document.getElementById('btnRestoreChat').addEventListener('click', restoreChatPanel);
    document.getElementById('justification_text').addEventListener('input', updatePostEvaluationActions);
    
    // Add listener for Enter key in chat input
    document.getElementById('chatInput').addEventListener('keypress', function (e) {
        if (e.key === 'Enter') {
            sendChatMessage();
        }
    });

    // Add listener for bonus slider
    document.getElementById('bonus_slider').addEventListener('input', (e) => {
        document.getElementById('bonus_value').innerText = `$${e.target.value}`;
        STATE.hasAdjustedBonusSlider = true;
        updateBonusSliderState();
    });

    const consentCheckbox = document.getElementById('consentCheckbox');
    const btnStartStudy = document.getElementById('btnStartStudy');
    const consentModal = new bootstrap.Modal(document.getElementById('consentModal'), {
        backdrop: 'static',
        keyboard: false
    });

    consentCheckbox.addEventListener('change', () => {
        btnStartStudy.disabled = !consentCheckbox.checked;
    });
    btnStartStudy.addEventListener('click', async () => {
        btnStartStudy.disabled = true;
        const initialized = await initializeSession();
        if (initialized) {
            consentModal.hide();
        } else {
            btnStartStudy.disabled = false;
        }
    });

    if (hasActiveParticipantSession) {
        const initialized = await initializeSession();
        if (initialized) {
            consentModal.hide();
        } else {
            consentModal.show();
        }
    } else {
        consentModal.show();
    }

});
