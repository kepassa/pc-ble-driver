/* Copyright (c) 2013 Nordic Semiconductor. All Rights Reserved.
 *
 * The information contained herein is property of Nordic Semiconductor ASA.
 * Terms and conditions of usage are described in detail in NORDIC
 * SEMICONDUCTOR STANDARD SOFTWARE LICENSE AGREEMENT.
 *
 * Licensees are granted free, non-transferable use of the information. NO
 * WARRANTY of ANY KIND is provided. This heading must NOT be removed from
 * the file.
 *
 */

#ifndef TIMER_BOOST_H
#define TIMER_BOOST_H

#include "timer.h"


/**@brief Timer class that uses the boost asio deadline_timer class*/
class TimerBoost : public Timer
{
private:
    /**@brief Default constructor */
    TimerBoost();

public:
    /**@brief Constructor that fully initializes the timer*/
    TimerBoost(const uint32_t timeoutMs, const TimerMode timerMode,
               timer_handler_t timerHandler);

    /**brief Destructor */
    ~TimerBoost();

    /**@brief Starts the timer with preconfigured timeout.
     **@note Multiple calls are ignored while the timer is running */
    uint32_t startTimer();

    /**@brief Starts the timer with a timeout given in ms.
     **@note Multiple calls are ignored while the timer is running */
    uint32_t startTimer(const uint32_t timeoutMs);

    /**@brief Stops the timer immediately */
    uint32_t stopTimer();
    
    /* Mock specific methods */
    static TimerBoost *getInstance();
    void resetMockVariables();
    void triggerTimeoutCallback();
    void setResponseValue(uint32_t value);
    uint32_t getTimeoutValue();
    TimerMode getTimerMode();
    bool wasStopTimerCalled();
    bool wasStartTimerCalled();

private:
    enum TimerState
    {
        TimerIdle,
        TimerRunning,
        TimerStopped,
    };
    
    static TimerBoost *instance;
    TimerState timerState;
    uint32_t responseValue;
    bool stopTimerCalled;
    bool startTimerCalled;
};

#endif // TIMER_BOOST_H
